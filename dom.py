import asyncio
import logging
import time

log = logging.getLogger("dom")

JS_FIND = r"""
(kind) => {
  const vis = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden'
           && s.display !== 'none' && s.opacity !== '0';
  };
  const rect = el => {
    const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height};
  };
  const attr = el => [el.placeholder, el.name, el.id,
                      el.getAttribute('aria-label')].join(' ').toLowerCase();

  const inputs = [...document.querySelectorAll('input,textarea')].filter(vis);

  if (kind === 'mobile') {
    const el = inputs.find(i => /mobile|phone|number|whatsapp/.test(attr(i))
      || i.type === 'tel' || i.type === 'number'
      || i.inputMode === 'numeric' || i.inputMode === 'tel');
    return el ? rect(el) : null;
  }
  if (kind === 'password') {
    const el = inputs.find(i => i.type === 'password');
    return el ? rect(el) : null;
  }
  if (kind === 'invite') {
    const el = inputs.find(i => /invite|referr|refer|bonus|code/.test(attr(i))
      && !/captcha|otp/.test(attr(i)));
    return el ? rect(el) : null;
  }
  if (kind === 'checkbox') {
    const el = [...document.querySelectorAll('input[type=checkbox]')].filter(vis)[0];
    return el ? rect(el) : null;
  }
  if (kind === 'submit') {
    const all = [...document.querySelectorAll('button,[role=button],div,span')].filter(vis);
    const el = all.find(b => {
      const t = (b.innerText || '').trim();
      return /^(register|sign\s*up|create|continue|submit)/i.test(t)
             && b.getBoundingClientRect().width > 80;
    });
    return el ? rect(el) : null;
  }
  return null;
}
"""

# captcha widget ko main frame + har iframe me dhoondhta hai.
# mile to data-cc marker lagata hai, phir locator se pakda jaata hai.
JS_MARK = r"""
() => {
  document.querySelectorAll('[data-cc]').forEach(e => e.removeAttribute('data-cc'));
  const vis = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden'
           && s.display !== 'none' && s.opacity !== '0';
  };
  const bgs = [...document.querySelectorAll('canvas, img')].filter(vis).filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 120 && r.height > 50 && r.height < 400;
  });
  for (const bg of bgs) {
    let node = bg.parentElement;
    for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
      const kids = [...node.querySelectorAll('div,span,button,a')].filter(vis);
      const handle = kids.find(k => {
        const r = k.getBoundingClientRect();
        if (r.width < 16 || r.width > 80 || r.height < 16 || r.height > 80) return false;
        const cls = k.getAttribute('class') || '';
        const cur = getComputedStyle(k).cursor;
        return /slide|handle|drag|thumb|swipe|btn/i.test(cls)
            || cur === 'grab' || cur === 'move' || cur === 'ew-resize';
      });
      if (!handle) continue;
      const hr = handle.getBoundingClientRect();
      const br = bg.getBoundingClientRect();
      if (hr.y + hr.height / 2 > br.y + br.height * 0.55) {
        bg.setAttribute('data-cc', 'img');
        handle.setAttribute('data-cc', 'handle');
        return true;
      }
    }
  }
  return false;
}
"""

JS_PASSED = r"""
() => {
  const bad = /error|invalid|fail|galat/i;
  const boxes = [...document.querySelectorAll('div,span')]
    .filter(el => bad.test(el.className || '') && el.getBoundingClientRect().width > 20);
  if (boxes.length) return false;

  const btns = [...document.querySelectorAll('button,[role=button]')]
    .filter(b => /register|sign\s*up|continue|submit/i.test(b.innerText || ''));
  if (!btns.length) return null;
  const b = btns[0];
  return !(b.disabled || /disabled|is-gray|grayed/i.test(b.className));
}
"""


async def find(page, kind: str) -> dict | None:
    try:
        r = await page.evaluate(JS_FIND, kind)
    except Exception:
        log.debug("find %s fail", kind, exc_info=True)
        return None
    if r:
        log.debug("found %s at %dx%d", kind, int(r["x"]), int(r["y"]))
    return r


async def find_captcha(page):
    """(img_locator, handle_locator) — sab frames me. Nahi mila to None."""
    for frame in page.frames:
        try:
            if not await frame.evaluate(JS_MARK):
                continue
            img = frame.locator('[data-cc="img"]').first
            handle = frame.locator('[data-cc="handle"]').first
            if await img.count() and await handle.count():
                log.debug("captcha frame=%s", frame.url[:70])
                return img, handle
        except Exception:
            continue
    return None


async def wait_captcha(page, timeout_ms: int = 10000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        w = await find_captcha(page)
        if w:
            return w
        await asyncio.sleep(0.4)
    return None


def center(r: dict) -> tuple[float, float]:
    return r["x"] + r["w"] / 2, r["y"] + r["h"] / 2


async def click(page, r: dict) -> None:
    x, y = center(r)
    await page.mouse.click(x, y)


async def fill(page, r: dict, text: str) -> None:
    x, y = center(r)
    await page.mouse.click(x, y)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(text, delay=60)


async def passed(page) -> bool | None:
    try:
        return await page.evaluate(JS_PASSED)
    except Exception:
        return None