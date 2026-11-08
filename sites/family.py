import logging

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from captcha import slider, solver_api
from config import settings
from identity import fingerprint
from sites.base import RegisterError

log = logging.getLogger("site")


class FamilyAdapter:
    slug = ""

    def __init__(self, doc: dict):
        self.doc = doc
        self.sel = doc["selectors"]
        self.pad_right = doc.get("pad_right", 0)
        self.url = f"{doc['base_url'].rstrip('/')}/#/register"

    async def validate_invite(self, code: str) -> bool:
        return len(code.strip()) >= 4

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
                log.info("%s api fallback", tag)
                await solver_api.solve(b64)

            try:
                await page.click(self.sel["captcha_refresh"], timeout=3000)
                log.info("%s captcha refresh click", tag)
                await page.wait_for_timeout(700)
            except PWTimeout:
                log.warning("%s refresh button nahi mila, reload", tag)
                await page.reload(wait_until="domcontentloaded")
                await page.wait_for_selector(self.sel["form_ready"], timeout=settings.form_ms)

        return False

    async def register(self, ident: dict, proxy: str | None) -> dict:
        fp = fingerprint()
        tag = ident["username"]
        log.info("%s launch proxy=%s", tag, proxy or "DIRECT")

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
            try:
                log.info("%s goto", tag)
                await page.goto(self.url, wait_until="domcontentloaded", timeout=settings.goto_ms)
                log.info("%s form wait", tag)
                await page.wait_for_selector(self.sel["form_ready"], timeout=settings.form_ms)
                log.info("%s form mila url=%s", tag, page.url)

                await page.fill(self.sel["mobile"], ident["mobile"])
                await page.fill(self.sel["password"], ident["password"])
                log.info("%s creds bhare", tag)

                if ident.get("invite_code"):
                    try:
                        await page.fill(self.sel["invite"], ident["invite_code"], timeout=2500)
                        log.info("%s invite bhara", tag)
                    except PWTimeout:
                        log.warning("%s invite field nahi mila", tag)

                if not await self._solve(page, tag):
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
            except PWTimeout as e:
                log.error("%s timeout: %s", tag, str(e)[:160])
                raise RegisterError("timeout / no redirect")
            finally:
                try:
                    await ctx.close()
                finally:
                    await browser.close()
                log.info("%s browser band", tag)

        return {"username": ident["username"], "password": ident["password"]}