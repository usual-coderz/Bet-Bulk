import asyncio
import random
import time
from pathlib import Path

import httpx

SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
]

CACHE = Path("proxy_cache.txt")
TEST_URL = "https://www.dmplay20.com/"
MIN_POOL = 15
DEAD_COOLDOWN = 1800
MAX_VALIDATE = 400

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
    if len(parts) < 2:
        return None
    host, port = parts[0], parts[1]
    if not port.isdigit():
        return None
    return f"http://{host}:{port}"


async def _fetch_source(c: httpx.AsyncClient, url: str) -> set[str]:
    try:
        r = await c.get(url, timeout=25)
        if r.status_code != 200:
            return set()
        return {p for p in (_norm(l) for l in r.text.splitlines()) if p}
    except Exception:
        return set()


async def _check(c: httpx.AsyncClient, proxy: str, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        try:
            r = await c.get(TEST_URL, proxy=proxy, timeout=8, follow_redirects=True)
            if r.status_code < 500:
                return proxy
        except Exception:
            return None
    return None


async def refresh(force: bool = False) -> int:
    global _last_refresh
    async with _lock:
        if not force and _pool and time.time() - _last_refresh < 600:
            return len(_pool)

        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True
        ) as c:
            batches = await asyncio.gather(*(_fetch_source(c, u) for u in SOURCES))
            raw = set().union(*batches)

        raw -= set(_pool)
        raw = list(raw)[:MAX_VALIDATE]
        if not raw:
            _last_refresh = time.time()
            return len(_pool)

        sem = asyncio.Semaphore(120)
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as c:
            results = await asyncio.gather(*(_check(c, p, sem) for p in raw))

        good = [p for p in results if p]
        random.shuffle(good)

        merged = list(dict.fromkeys(good + _pool))[:120]
        _pool[:] = merged
        _last_refresh = time.time()

        CACHE.write_text("\n".join(_pool))
        return len(_pool)


def _load_cache() -> None:
    if CACHE.exists():
        _pool.extend(p for p in (_norm(l) for l in CACHE.read_text().splitlines()) if p)


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


async def maintain(stop: asyncio.Event, interval: int) -> None:
    _load_cache()
    while not stop.is_set():
        try:
            await refresh()
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass