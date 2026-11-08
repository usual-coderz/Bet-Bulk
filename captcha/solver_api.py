import asyncio
import httpx
from config import settings

BASE = "https://2captcha.com"


async def solve(img_b64: str) -> int | None:
    if not settings.captcha_key:
        return None
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{BASE}/in.php", data={
            "key": settings.captcha_key, "method": "base64", "body": img_b64,
            "coordinatescaptcha": 1, "json": 1,
            "textinstructions": "slide puzzle: return center x of the puzzle-shaped gap",
        })
        rid = r.json().get("request")
        if not rid:
            return None
        for _ in range(30):
            await asyncio.sleep(3)
            g = await c.get(f"{BASE}/res.php",
                            params={"key": settings.captcha_key, "action": "get", "id": rid, "json": 1})
            d = g.json()
            if d.get("status") == 1:
                return int(d["request"].split(",")[0])
            if "CAPCHA_NOT_READY" not in str(d.get("request")):
                return None
    return None