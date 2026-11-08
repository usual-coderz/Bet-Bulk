import logging

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from config import settings

log = logging.getLogger("db")

_client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=8000)
db = _client[settings.mongo_db]

sites = db["sites"]
invite_codes = db["invite_codes"]
jobs = db["jobs"]
credentials = db["credentials"]
proxy_cache = db["proxy_cache"]


async def init_indexes() -> None:
    await sites.create_index("slug", unique=True)
    await invite_codes.create_index([("site_slug", ASCENDING), ("code", ASCENDING)], unique=True)
    await jobs.create_index("status")
    await jobs.create_index("created_at")
    await credentials.create_index("job_id")
    log.info("indexes ready")


async def ping() -> None:
    await db.command("ping")


async def close() -> None:
    _client.close()


__all__ = [
    "db", "sites", "invite_codes", "jobs", "credentials", "proxy_cache",
    "init_indexes", "ping", "close", "DuplicateKeyError",
]