import asyncio
import logging
import time
from pathlib import Path

from playwright.async_api import async_playwright, Error as PWError, TimeoutError as PWTimeout

import dom
from captcha import slider, solver_api
from config import settings
from identity import fingerprint
from sites.base import CaptchaError, FormError, ProxyError, RegisterError

log = logging.getLogger("site")
DUMP_DIR = Path("logs/dumps")

PROXY_ERRS = (
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_AUTH",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_EMPTY_RESPONSE",
)


class FamilyAdapter:
    slug = ""

    def __init__(self, doc: dict):
        self.doc = doc
        self.sel = doc["selectors"]
        self.pad_right = doc.get("pad_right", 0)
        self.base = doc["base_url"].rstrip("/")
        self.url = f"{self.base}/#/register"

    async def validate_invite(self, code: str) -> bool:
        return len(code.strip()) >= 4

    async def _dump(self, page, tag: str, reason: str) -> None:
        if not settings.debug_dump:
            return
        DUMP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        try:
            await page.screenshot(path=str(DUMP_DIR / f"{tag}-{reason}-{stamp}.png"),
                                  full_page=True)
            html = await page.content()
            (DUMP_DIR / f"{tag}-{reason}-{stamp}.html").write_text(html, encoding="utf-8")
            frames = " | ".join(f.url for f in page.frames)
            (DUMP_DIR / f"{tag}-{reason}-{stamp}.frames").write_text(frames, encoding="utf-8")
            log.info("%s dump: %s-%s (%d frames)", tag, reason, stamp, len(page.frames))
        except Exception:
            log.debug("%s dump fail", tag, exc_info=True)

    async def _wait_mobile(self, page, tag: str) -> dict:
        deadline = time.monotonic() + settings.form_ms / 1000
        while time.monotonic() < deadline:
            r = await dom.find(page, "mobile")
            if r:
                return r
            await asyncio.sleep(0.5)

        log.error("%s mobile input nahi mila title=%r url=%s",
                  tag, await page.title(), page.url)
        await self._dump(page, tag, "no_mobile")
        raise FormError("mobile input nahi mila")

    async def _fill_form(self, page, ident: dict, tag: str) -> None:
        mobile_r = await self._wait_mobile(page, tag)
        await dom.fill(page, mobile_r, ident["mobile"])
        log.info("%s mobile bhara", tag)

        pw_r = await dom.find(page, "password")
        if not pw_r:
            await self._dump(page, tag, "no_password")
            raise FormError("password input nahi mila")
        await dom.fill(page, pw_r, ident["password"])
        log.info("%s password bhara", tag)

        if ident.get("invite_code"):
            inv_r = await dom.find(page, "invite")
            if inv_r:
                await dom.fill(page, inv_r, ident["invite_code"])
                log.info("%s invite bhara", tag)
            else:
                log.warning("%s invite field nahi mila", tag)

        await page.keyboard.press("Tab")

    async def _reload(self, page, ident: dict, tag: str) -> None:
        log.info("%s captcha reload", tag)
        await page.reload(wait_until="domcontentloaded")
        await self._fill_form(page, ident, tag)

    async def _verify(self, page, tag: str) -> bool:
        await page.wait_for_timeout(900)
        passed = await dom.passed(page)
        log.info("%s passed=%s", tag, passed)
        return passed is not False

    async def _solve(self, page, ident: dict, tag: str) -> bool:
        for n in (1, 2):
            log.info("%s captcha attempt=%d", tag, n)

            w = await dom.wait_captcha(page, settings.captcha_ms)
            if not w:
                log.warning("%s widget %dms me nahi aaya", tag, settings.captcha_ms)
                await self._dump(page, tag, "no_widget")
                await self._reload(page, ident, tag)
                continue

            res = await slider.slide(page, self.sel, self.pad_right)
            log.info("%s slide ok=%s distance=%d", tag, res.ok, res.distance)

            if res.ok and await self._verify(page, tag):
                log.info("%s captcha PASS (cv)", tag)
                return True

            b64 = await slider.screenshot_b64(page, self.sel)
            hint = await solver_api.solve(b64) if b64 else None
            if hint is not None:
                res = await slider.slide(page, self.sel, self.pad_right, x_hint=hint)
                log.info("%s solver slide ok=%s distance=%d", tag, res.ok, res.distance)
                if res.ok and await self._verify(page, tag):
                    log.info("%s captcha PASS (api)", tag)
                    return True

            await self._reload(page, ident, tag)

        return False

    async def register(self, ident: dict, proxy: str | None) -> dict:
        fp = fingerprint()
        tag = ident["username"]
        goto_ms = settings.goto_ms_proxy if proxy else settings.goto_ms

        log.info("%s launch proxy=%s goto_ms=%d", tag, proxy or "DIRECT", goto_ms)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.headless,
                proxy={"server": proxy} if proxy else None,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = await browser.new_context(
                user_agent=fp["ua"],
                viewport=fp["viewport"],
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                is_mobile=True,
                has_touch=True,
                device_scale_factor=2,
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome={runtime:{}};"
            )
            page = await ctx.new_page()
            page.set_default_timeout(10000)

            try:
                log.info("%s goto", tag)
                try:
                    await page.goto(self.url, wait_until="domcontentloaded", timeout=goto_ms)
                except PWTimeout:
                    await self._dump(page, tag, "goto_timeout")
                    if proxy:
                        raise ProxyError("goto timeout via proxy")
                    raise RegisterError("goto timeout")
                except PWError as e:
                    msg = str(e)
                    if proxy and any(k in msg for k in PROXY_ERRS):
                        log.warning("%s proxy dead: %s", tag, msg[:80])
                        await self._dump(page, tag, "proxy_dead")
                        raise ProxyError(msg[:120])
                    raise RegisterError(msg[:120])

                log.info("%s loaded title=%r", tag, await page.title())
                await self._fill_form(page, ident, tag)

                if not await self._solve(page, ident, tag):
                    await self._dump(page, tag, "captcha_fail")
                    raise CaptchaError("captcha unsolved")

                cb_r = await dom.find(page, "checkbox")
                if cb_r:
                    await dom.click(page, cb_r)
                    log.info("%s checkbox clicked", tag)

                sub_r = await dom.find(page, "submit")
                if not sub_r:
                    await self._dump(page, tag, "no_submit")
                    raise FormError("submit button nahi mila")

                log.info("%s submit click", tag)
                await dom.click(page, sub_r)

                await page.wait_for_function(
                    "() => !location.hash.includes('register')", timeout=settings.redirect_ms)
                log.info("%s SUCCESS url=%s", tag, page.url)

            except PWTimeout:
                log.error("%s timeout url=%s", tag, page.url)
                await self._dump(page, tag, "timeout")
                raise RegisterError("timeout / no redirect")
            finally:
                try:
                    await ctx.close()
                finally:
                    await browser.close()
                log.info("%s browser band", tag)

        return {"username": ident["username"], "password": ident["password"]}