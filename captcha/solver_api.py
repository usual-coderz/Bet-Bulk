import asyncio
import logging

import httpx

from config import settings

log = logging.getLogger("captcha_api")
BASE = "https://2captcha.com"


async def solve(img_b64: str) -> int | None:
    if not settings.captcha_key:
        log.debug("captcha key nahi hai, fallback skip")
        return None

    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{BASE}/in.php", data={
                "key": settings.captcha_key,
                "method": "base64",
                "body": img_b64,
                "coordinatescaptcha": 1,
                "json": 1,
                "textinstructions": "slide puzzle: return center x of the puzzle gap",
            })
            rid = r.json().get("request")
            if not rid:
                log.warning("2captcha submit reject: %s", r.text[:120])
                return None

            log.info("2captcha task %s", rid)
            for _ in range(30):
                await asyncio.sleep(3)
                g = await c.get(f"{BASE}/res.php",
                                params={"key": settings.captcha_key, "action": "get",
                                        "id": rid, "json": 1})
                d = g.json()
                if d.get("status") == 1:
                    x = int(d["request"].split(",")[0])
                    log.info("2captcha answer x=%d", x)
                    return x
                if "CAPCHA_NOT_READY" not in str(d.get("request")):
                    log.warning("2captcha fail: %s", d)
                    return None
    except Exception:
        log.exception("2captcha error")
    return None