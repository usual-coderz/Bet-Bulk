import asyncio
import logging

import httpx

from config import settings

log = logging.getLogger("captcha_api")
BASE = "https://2captcha.com"

RETRYABLE = {"CAPCHA_NOT_READY", "ERROR_NO_SLOT_AVAILABLE"}


async def solve(img_b64: str) -> int | None:
    """Gap center ka x (CSS px). None = koi jawab nahi."""
    if not settings.captcha_key:
        log.debug("captcha key nahi hai, fallback skip")
        return None

    try:
        async with httpx.AsyncClient(timeout=90) as c:
            rid = None
            for attempt in range(3):
                r = await c.post(f"{BASE}/in.php", data={
                    "key": settings.captcha_key,
                    "method": "base64",
                    "body": img_b64,
                    "coordinatescaptcha": 1,
                    "json": 1,
                    "textinstructions": "slider puzzle: click center of the empty gap",
                })
                data = r.json()
                rid = data.get("request")
                if rid:
                    break
                if "ERROR_NO_SLOT" in str(rid):
                    await asyncio.sleep(4)
                    continue
                log.warning("2captcha submit reject: %s", r.text[:140])
                return None

            if not rid:
                return None

            log.info("2captcha task %s", rid)
            for _ in range(30):
                await asyncio.sleep(3)
                g = await c.get(f"{BASE}/res.php", params={
                    "key": settings.captcha_key, "action": "get",
                    "id": rid, "json": 1})
                d = g.json()
                if d.get("status") == 1:
                    x = int(float(d["request"].split(",")[0]))
                    log.info("2captcha answer x=%d", x)
                    return x
                msg = str(d.get("request"))
                if not any(k in msg for k in RETRYABLE):
                    log.warning("2captcha fail: %s", d)
                    return None
    except Exception:
        log.exception("2captcha error")
    return None