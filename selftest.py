import logging

from config import settings
from db import ping
from proxies import size, refresh

log = logging.getLogger("selftest")


async def run() -> None:
    problems = []

    try:
        await ping()
        log.info("mongo OK")
    except Exception as e:
        problems.append(f"mongo: {e}")

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            log.info("chromium OK %s", b.version)
            await b.close()
    except Exception as e:
        problems.append(
            f"chromium: {e}\n-> chalao: playwright install --with-deps chromium"
        )

    try:
        n = await refresh(force=True)
        log.info("proxy pool %d", n)
        if n == 0:
            problems.append("proxy pool khaali")
    except Exception as e:
        problems.append(f"proxy fetch: {e}")

    if not settings.admins:
        problems.append("ADMIN_IDS khaali (diag commands kaam nahi karengi)")

    if problems:
        raise SystemExit("SELFTEST FAIL:\n- " + "\n- ".join(problems))

    log.info("selftest pass")