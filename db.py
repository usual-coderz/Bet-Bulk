from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError
from config import settings

_client = AsyncIOMotorClient(settings.mongo_url)
db = _client[settings.mongo_db]

sites = db["sites"]
invite_codes = db["invite_codes"]
jobs = db["jobs"]
credentials = db["credentials"]


async def init_indexes():
    await sites.create_index("slug", unique=True)
    await invite_codes.create_index([("site_slug", ASCENDING), ("code", ASCENDING)], unique=True)
    await jobs.create_index("status")
    await jobs.create_index("created_at")
    await credentials.create_index("job_id")


__all__ = ["db", "sites", "invite_codes", "jobs", "credentials", "init_indexes", "DuplicateKeyError"]