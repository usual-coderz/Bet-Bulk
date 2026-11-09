import inspect
import logging

import httpx

log = logging.getLogger("httpx_compat")

# 0.26+ me `proxy=`, usse pehle `proxies=`
_NEW_API = "proxy" in inspect.signature(httpx.AsyncClient.__init__).parameters

if not _NEW_API:
    log.warning("httpx %s purana hai, `proxies=` use kar rahe hain (0.27+ pe upgrade karo)",
                httpx.__version__)


def client_kwargs(proxy: str | None) -> dict:
    if not proxy:
        return {}
    return {"proxy": proxy} if _NEW_API else {"proxies": proxy}


def describe() -> str:
    return f"httpx {httpx.__version__} ({'proxy' if _NEW_API else 'proxies'})"