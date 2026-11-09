from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


BASE_SELECTORS = {
    "form_ready": "input[type=tel]",
    "form_ready_alt": [
        "input[placeholder*='obile']",
        "input[placeholder*='hone']",
        "input[placeholder*='umber']",
        "input[inputmode='numeric']",
        "input[type=number]",
        "input[name*=mobile]",
        "input[name*=phone]",
    ],
    "mobile": "input[type=tel]",
    "password": "input[type=password]",
    "invite": "input[name*=invite]",
    "agree": "input[type=checkbox]",
    "submit": "button:has-text('Register')",
    "captcha_img": ".captcha-img",
    "slider_handle": ".slider-handle",
    "captcha_refresh": ".captcha-refresh",
}


def site_doc(slug: str, name: str, base_url: str,
             selectors: dict | None = None, pad_right: int = 0) -> dict:
    merged = dict(BASE_SELECTORS)
    if selectors:
        merged.update(selectors)
    return {
        "slug": slug,
        "name": name,
        "enabled": True,
        "base_url": base_url,
        "pad_right": pad_right,
        "selectors": merged,
        "created_at": now(),
    }


def job_doc(tg_id: int, site_slug: str, invite_code: str, count: int, gap_sec: int) -> dict:
    return {
        "tg_id": tg_id,
        "site_slug": site_slug,
        "invite_code": invite_code,
        "count": count,
        "gap_sec": gap_sec,
        "done": 0,
        "failed": 0,
        "status": "queued",
        "progress_msg_id": None,
        "error": None,
        "created_at": now(),
        "claimed_at": None,
        "finished_at": None,
    }


def cred_doc(job_id, site_slug: str, username: str, password_enc: str,
             mobile: str, status: str = "ok", error: str | None = None) -> dict:
    return {
        "job_id": job_id,
        "site_slug": site_slug,
        "username": username,
        "password_enc": password_enc,
        "mobile": mobile,
        "status": status,
        "error": error,
        "created_at": now(),
    }