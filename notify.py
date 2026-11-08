# notify.py
import httpx
from config import settings

API = f"https://api.telegram.org/bot{settings.bot_token}"


def edit(chat_id: int, message_id: int, text: str) -> None:
    try:
        httpx.post(f"{API}/editMessageText", json={
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "parse_mode": "HTML",
        }, timeout=15)
    except Exception:
        pass


def send_document(chat_id: int, path: str, caption: str = "") -> None:
    try:
        with open(path, "rb") as f:
            httpx.post(f"{API}/sendDocument",
                       data={"chat_id": chat_id, "caption": caption},
                       files={"document": f}, timeout=60)
    except Exception:
        pass