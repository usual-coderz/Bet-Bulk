import asyncio
import logging
import time
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from captcha import slider, solver_api
from config import settings
from identity import fingerprint
from sites.base import RegisterError

log = logging.getLogger("site")
DUMP_DIR = Path("logs/dumps")


class FamilyAdapter:
    slug = ""

    def __init__(self, doc: dict):
        self.doc = doc
        self.sel = doc["selectors"]
        self.pad_right = doc.get("pad_right", 0)
        self.url = f"{doc['base_url'].rstrip('/')}/#/register"

    async def validate_invite(self, code: str) -> bool:
        return len(code.strip()) >= 4

    async def _dump(self, page, tag: str, reason: str) -> None:
        if not settings.debug_dump:
            return
        DUMP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        try:
            await page.screenshot(path=str(DUMP_DIR / f"{tag}-{stamp}.png"), full_page=False)
            html = await page.content()
            (DUMP_DIR / f"{tag}-{stamp}.html").write_text(html, encoding="utf-8")
            log.info("%s dump likha: %s-%s", tag, reason, stamp)
        except Exception:
            log.debug("%s dump fail", tag, exc_info=True)

    async def _wait_form(self, page, tag: str) -> str:
        sels = self.sel.get("form_ready", [])
        if isinstance(sels, str):
            sels = [sels]
        sels = list(sels) + list(self.sel.get("form_ready_alt", []))

        deadline = time.monotonic() + settings.form_ms / 1000
        while time.monotonic() < deadline:
            for s in sels:
                try:
                    loc = page.locator(s).first
                    if await loc.count() and await loc.is_visible():
                        return s
                except Exception:
                    continue
            await asyncio.sleep(0.5)

        log.error("%s form selector nahi mila. title=%r url=%s", tag, await page.title(), page.url)
        await self._dump(page, tag, "form_missing")
        raise RegisterError("form selector nahi mila")

    async def _solve(self, page, tag: str) -> bool:
        for n in range(1, 4):
            log.info("%s captcha attempt=%d", tag, n)
            res = await slider.slide(page, self.sel, self.pad_right)
            log.info("%s slide ok=%s distance=%d", tag, res.ok, res.distance)

            if res.ok:
                await page.wait_for_timeout(800)
                if await page.locator(self.sel["submit"]).first.is_enabled():
                    log.info("%s captcha PASS", tag)
                    return True
                log.warning("%s captcha reject (button disabled)", tag)

            b64 = await slider.screenshot_b64(page, self.sel)
            if b64:
                await solver_api.solve(b64)

            try:
                await page.click(self.sel["captcha_refresh"], timeout=3000)
                log.info("%s captcha refresh", tag)
                await page.wait_for_timeout(700)
            except PWTimeout:
                log.warning("%s refresh nahi mila, reload", tag)
                await page.reload(wait_until="domcontentloaded")
                await self._wait_form(page, tag)

        return False

    async def register(self, ident: dict, proxy: str | None) -> dict:
        fp = fingerprint()
        tag = ident["username"]
        goto_ms = settings.goto_ms if not proxy else settings.goto_ms_proxy

        log.info("%s launch proxy=%s goto_ms=%d", tag, proxy or "DIRECT", goto_ms)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.headless,
                proxy={"server": proxy} if proxy else None,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
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
                    log.error("%s goto timeout", tag)
                    await self._dump(page, tag, "goto_timeout")
                    raise RegisterError("goto timeout")

                log.info("%s loaded title=%r url=%s", tag, await page.title(), page.url)

                if "register" not in page.url:
                    log.warning("%s register route se hat gaya: %s", tag, page.url)

                ready = await self._wait_form(page, tag)
                log.info("%s form mila via %r", tag, ready)

                await page.fill(ready, ident["mobile"])
                await page.fill(self.sel["password"], ident["password"])
                log.info("%s creds bhare", tag)

                if ident.get("invite_code"):
                    try:
                        await page.fill(self.sel["invite"], ident["invite_code"], timeout=2500)
                        log.info("%s invite bhara", tag)
                    except PWTimeout:
                        log.warning("%s invite field nahi mila", tag)

                if not await self._solve(page, tag):
                    await self._dump(page, tag, "captcha_fail")
                    raise RegisterError("captcha unsolved")

                try:
                    await page.check(self.sel["agree"], timeout=5000)
                except PWTimeout:
                    log.warning("%s checkbox nahi mila", tag)

                log.info("%s submit click", tag)
                await page.click(self.sel["submit"])
                await page.wait_for_function(
                    "() => !location.hash.includes('register')", timeout=settings.redirect_ms
                )
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