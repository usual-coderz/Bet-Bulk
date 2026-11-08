import asyncio
from db import init_indexes, sites
from schemas import site_doc

SEED = [
    site_doc("khelv2", "KhelV2", "https://www.khelv2.com"),
    site_doc("dmplay20", "DMPlay20", "https://www.dmplay20.com"),
    site_doc("dmfirst11", "DMFirst11", "https://www.dmfirst11.com"),
    site_doc("raxi", "Raxi", "https://www.raxi.bio"),
]


async def main():
    await init_indexes()
    for s in SEED:
        await sites.update_one({"slug": s["slug"]}, {"$setOnInsert": s}, upsert=True)
    print("seeded 4 sites")


if __name__ == "__main__":
    asyncio.run(main())