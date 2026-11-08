import logging

import httpx

from config import settings

log = logging.getLogger("notify")
API = f"https://api.telegram.org/bot{settings.bot_token}"


def edit(chat_id: int, message_id: int, text: str) -> None:
    try:
        httpx.post(f"{API}/editMessageText", json={
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "parse_mode": "HTML",
        }, timeout=15)
    except Exception:
        log.debug("edit fail chat=%s msg=%s", chat_id, message_id, exc_info=True)


def send(chat_id: int, text: str) -> None:
    try:
        httpx.post(f"{API}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        }, timeout=15)
    except Exception:
        log.warning("send fail chat=%s", chat_id, exc_info=True)


def send_document(chat_id: int, path: str, caption: str = "") -> None:
    try:
        with open(path, "rb") as f:
            httpx.post(f"{API}/sendDocument",
                       data={"chat_id": chat_id, "caption": caption},
                       files={"document": f}, timeout=60)
    except Exception:
        log.warning("document fail chat=%s path=%s", chat_id, path, exc_info=True)


def alert_admins(text: str) -> None:
    for uid in settings.admins:
        send(uid, text)