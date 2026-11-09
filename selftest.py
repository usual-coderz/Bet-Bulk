import logging

from config import settings
from db import ping
from httpx_compat import describe
from proxies import refresh, size

log = logging.getLogger("selftest")


async def run() -> None:
    fatal: list[str] = []
    warn: list[str] = []

    log.info("httpx: %s", describe())

    try:
        await ping()
        log.info("mongo OK")
    except Exception as e:
        fatal.append(f"mongo: {e}")

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            log.info("chromium OK %s", b.version)
            await b.close()
    except Exception as e:
        fatal.append(f"chromium: {e}\n-> chalao: playwright install --with-deps chromium")

    if settings.proxy_mode != "off":
        try:
            n = await refresh(force=True)
            log.info("proxy pool %d", n)
            if n == 0:
                warn.append("proxy pool 0 — DIRECT mode me chalega, par rate-limit jaldi aayegi")
            elif n < 10:
                warn.append(f"proxy pool sirf {n} — kam hai")
        except Exception as e:
            warn.append(f"proxy fetch: {e}")
    else:
        log.info("proxy_mode=off, skip")

    if not settings.admins:
        warn.append("ADMIN_IDS khaali")

    for w in warn:
        log.warning("WARN: %s", w)

    if fatal:
        raise SystemExit("SELFTEST FAIL:\n- " + "\n- ".join(fatal))

    log.info("selftest pass (warnings=%d)", len(warn))