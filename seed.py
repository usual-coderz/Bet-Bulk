import asyncio

from db import init_indexes, sites
from schemas import site_doc

SEED = [
    site_doc("khelv2", "KhelV2", "https://www.khelv2.com"),
    site_doc("dmplay20", "DMPlay20", "https://www.dmplay20.com"),
    site_doc("dmfirst11", "DMFirst11", "https://www.dmfirst11.com"),
    site_doc("raxi", "Raxi", "https://www.raxi.bio"),
]


async def main() -> None:
    await init_indexes()
    for s in SEED:
        # selectors/name/base_url update, pad_right force reset
        doc = dict(s)
        doc.pop("created_at", None)
        doc["pad_right"] = 0
        await sites.update_one(
            {"slug": s["slug"]},
            {"$set": doc, "$setOnInsert": {"created_at": s["created_at"]}},
            upsert=True,
        )
    print("4 sites seeded, pad_right=0")


if __name__ == "__main__":
    asyncio.run(main())