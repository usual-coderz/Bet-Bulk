import asyncio
import logging
import random
import time

import httpx

from config import settings
from db import proxy_cache

log = logging.getLogger("proxy")

SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
]

TEST_URL = "https://www.dmplay20.com/"
DEAD_COOLDOWN = 1800

_pool: list[str] = []
_dead: dict[str, float] = {}
_lock = asyncio.Lock()
_last_refresh = 0.0


def _norm(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("http"):
        line = line.split("://", 1)[1]
    parts = line.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return f"http://{parts[0]}:{parts[1]}"


async def _fetch(c: httpx.AsyncClient, url: str) -> set[str]:
    try:
        r = await c.get(url, timeout=25)
        if r.status_code != 200:
            log.warning("source %s -> %d", url[:50], r.status_code)
            return set()
        out = {p for p in (_norm(l) for l in r.text.splitlines()) if p}
        log.info("source %s -> %d raw", url[:50], len(out))
        return out
    except Exception as e:
        log.warning("source %s fail: %s", url[:50], e)
        return set()


async def _check(c: httpx.AsyncClient, proxy: str, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        try:
            r = await c.get(TEST_URL, proxy=proxy, timeout=8, follow_redirects=True)
            return proxy if r.status_code < 500 else None
        except Exception:
            return None


async def refresh(force: bool = False) -> int:
    global _last_refresh
    async with _lock:
        if not force and _pool and time.time() - _last_refresh < 600:
            return len(_pool)

        log.info("proxy refresh shuru (pool=%d)", len(_pool))
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"},
                                     follow_redirects=True) as c:
            raw = set().union(*(await asyncio.gather(*(_fetch(c, u) for u in SOURCES))))

        raw -= set(_pool)
        raw = list(raw)[: settings.max_validate]
        log.info("validate karne ke liye %d candidates", len(raw))
        if not raw:
            _last_refresh = time.time()
            return len(_pool)

        sem = asyncio.Semaphore(settings.validate_concurrency)
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as c:
            results = await asyncio.gather(*(_check(c, p, sem) for p in raw))

        good = [p for p in results if p]
        log.info("valid proxies: %d / %d", len(good), len(raw))

        random.shuffle(good)
        _pool[:] = list(dict.fromkeys(good + _pool))[:100]
        _last_refresh = time.time()

        if good:
            try:
                await proxy_cache.delete_many({})
                await proxy_cache.insert_many([{"proxy": p, "at": time.time()} for p in good])
            except Exception:
                log.warning("proxy cache save fail", exc_info=True)

        log.info("pool size ab %d", len(_pool))
        return len(_pool)


async def load() -> None:
    try:
        async for d in proxy_cache.find({}):
            if time.time() - d.get("at", 0) < 3600:
                _pool.append(d["proxy"])
        log.info("cache se %d proxy load", len(_pool))
    except Exception:
        log.warning("cache load fail", exc_info=True)


def pick() -> str | None:
    t = time.time()
    live = [p for p in _pool if _dead.get(p, 0) < t]
    if not live:
        _dead.clear()
        live = _pool
    return random.choice(live) if live else None


def mark_dead(proxy: str) -> None:
    _dead[proxy] = time.time() + DEAD_COOLDOWN


def size() -> int:
    return len(_pool)


async def maintain(stop: asyncio.Event) -> None:
    await load()
    while not stop.is_set():
        try:
            await refresh()
        except Exception:
            log.exception("refresh loop error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.proxy_refresh_sec)
        except asyncio.TimeoutError:
            pass