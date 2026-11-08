import asyncio
import random

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from captcha import slider, solver_api
from identity import fingerprint
from sites.base import RegisterError


class FamilyAdapter:
    """Chaaron sites ek hi platform family hain — selectors site doc se aate hain."""

    slug = ""

    def __init__(self, doc: dict):
        self.doc = doc
        self.sel = doc["selectors"]
        self.url = f"{doc['base_url'].rstrip('/')}/#/register"

    async def validate_invite(self, code: str) -> bool:
        return len(code.strip()) >= 4

    async def _solve(self, page) -> bool:
        for _ in range(3):
            if await slider.slide(page, self.sel):
                await page.wait_for_timeout(800)
                if await page.locator(self.sel["submit"]).first.is_enabled():
                    return True
            b64 = await slider.screenshot_b64(page, self.sel)
            if b64:
                await solver_api.solve(b64)      # fallback signal
            try:
                await page.click(self.sel["captcha_refresh"], timeout=3000)
                await page.wait_for_timeout(700)
            except PWTimeout:
                await page.reload(wait_until="domcontentloaded")
                await page.wait_for_selector(self.sel["form_ready"], timeout=25000)
        return False

    async def register(self, ident: dict, proxy: str | None) -> dict:
        fp = fingerprint()
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": proxy} if proxy else None,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                user_agent=fp["ua"], viewport=fp["viewport"],
                locale="en-IN", timezone_id="Asia/Kolkata",
                is_mobile=True, has_touch=True, device_scale_factor=2,
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome={runtime:{}};"
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_selector(self.sel["form_ready"], timeout=30000)

                await page.fill(self.sel["mobile"], ident["mobile"])
                await page.fill(self.sel["password"], ident["password"])
                if ident.get("invite_code"):
                    try:
                        await page.fill(self.sel["invite"], ident["invite_code"], timeout=2500)
                    except PWTimeout:
                        pass

                if not await self._solve(page):
                    raise RegisterError("captcha unsolved")

                try:
                    await page.check(self.sel["agree"], timeout=5000)
                except PWTimeout:
                    pass

                await page.click(self.sel["submit"])
                await page.wait_for_function(
                    "() => !location.hash.includes('register')", timeout=60000
                )
            except PWTimeout:
                raise RegisterError("no redirect after submit")
            finally:
                await ctx.close()
                await browser.close()

        return {"username": ident["username"], "password": ident["password"]}