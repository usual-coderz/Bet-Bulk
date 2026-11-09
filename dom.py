import logging

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

  if (kind === 'captcha') {
    const bgs = [...document.querySelectorAll('canvas, img')].filter(vis).filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 140 && r.height > 55 && r.height < 340;
    });
    for (const bg of bgs) {
      let node = bg.parentElement;
      for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
        const kids = [...node.querySelectorAll('div,span,button')].filter(vis);
        const handle = kids.find(k => {
          const r = k.getBoundingClientRect();
          if (r.width < 18 || r.width > 70 || r.height < 18 || r.height > 70) return false;
          const cls = k.getAttribute('class') || '';
          const cur = getComputedStyle(k).cursor;
          return /slide|handle|drag|thumb|btn/i.test(cls) || cur === 'grab' || cur === 'move';
        });
        if (handle) {
          const hr = handle.getBoundingClientRect();
          const br = bg.getBoundingClientRect();
          if (hr.y + hr.height / 2 > br.y + br.height - 14) {
            bg.scrollIntoView({block: 'center'});
            return {img: rect(bg), handle: rect(handle)};
          }
        }
      }
    }
    return null;
  }

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

JS_PASSED = r"""
() => {
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