from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_SELECTORS = {
    "form_ready": "input[type=tel]",
    "mobile": "input[type=tel]",
    "password": "input[type=password]",
    "invite": "input[name*=invite]",
    "agree": "input[type=checkbox]",
    "submit": "button:has-text('Register')",
    "captcha_img": ".captcha-img",
    "slider_handle": ".slider-handle",
    "captcha_refresh": ".captcha-refresh",
}


def site_doc(slug, name, base_url, selectors: dict | None = None) -> dict:
    return {
        "slug": slug,
        "name": name,
        "enabled": True,
        "base_url": base_url,
        "mode": "browser",
        "needs_captcha": True,
        "selectors": {**DEFAULT_SELECTORS, **(selectors or {})},
        "created_at": now(),
    }


def job_doc(tg_id, site_slug, invite_code, count, gap_sec) -> dict:
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
        "created_at": now(),
    }


def cred_doc(job_id, site_slug, username, password_enc, mobile, status="ok", error=None) -> dict:
    return {
        "job_id": job_id, "site_slug": site_slug, "username": username,
        "password_enc": password_enc, "mobile": mobile,
        "status": status, "error": error, "created_at": now(),
    }