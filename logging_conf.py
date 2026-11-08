import logging
import logging.handlers
import os
import sys

from config import settings

LOG_DIR = os.getenv("LOG_DIR", "logs")
FMT = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(name)-16s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()

    fh = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "betbot.log"), maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(FMT)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(FMT)
    root.addHandler(sh)

    for noisy in ("httpx", "httpcore", "asyncio", "aiogram.event", "pymongo"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def tail(n: int = 80) -> str:
    path = os.path.join(LOG_DIR, "betbot.log")
    if not os.path.exists(path):
        return "(log file nahi hai)"
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-n:]) or "(khaali)"