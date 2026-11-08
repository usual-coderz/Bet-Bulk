import asyncio
import secrets

import crypto
import notify
import pdfgen
from db import credentials, jobs, sites
from identity import mobile, password, username
from proxies import mark_dead, pick
from schemas import cred_doc, now
from sites.base import RegisterError
from sites.registry import build

BATCH = 6
STAGGER = (4, 9)
PER_SITE = 3

_sem: dict[str, asyncio.Semaphore] = {}


def _text(job: dict) -> str:
    return (f"<b>{job['site_slug']}</b>\n"
            f"done {job['done']} / {job['count']}  ·  failed {job['failed']}")


async def _one(job_id: str, site: dict, ident: dict) -> bool:
    adapter = build(site)
    sem = _sem.setdefault(site["slug"], asyncio.Semaphore(PER_SITE))
    err = "unknown"

    for attempt in range(3):
        proxy = pick()
        async with sem:
            try:
                await adapter.register(ident, proxy)
                credentials.insert_one(cred_doc(
                    job_id, site["slug"], ident["username"],
                    crypto.enc(ident["password"]), ident["mobile"]))
                return True
            except RegisterError as e:
                err = str(e)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            finally:
                if proxy:
                    mark_dead(proxy)
        await asyncio.sleep(3 + attempt * 4)

    credentials.insert_one(cred_doc(
        job_id, site["slug"], ident["username"],
        crypto.enc(ident["password"]), ident["mobile"], status="failed", error=err))
    return False


async def run_job(job_id: str):
    from bson import ObjectId

    oid = ObjectId(job_id)
    job = await jobs.find_one_and_update(
        {"_id": oid, "status": "queued"},
        {"$set": {"status": "running", "claimed_at": now()}},
    )
    if not job:
        return

    site = await sites.find_one({"slug": job["site_slug"], "enabled": True})
    if not site:
        await jobs.update_one({"_id": oid}, {"$set": {"status": "failed"}})
        return

    ok_rows = []

    for start in range(0, job["count"], BATCH):
        idents = [{
            "username": username(), "password": password(),
            "mobile": mobile(), "invite_code": job["invite_code"],
        } for _ in range(min(BATCH, job["count"] - start))]

        tasks = []
        for ident in idents:
            tasks.append(asyncio.create_task(_one(job_id, site, ident)))
            await asyncio.sleep(secrets.randint(*STAGGER))

        results = await asyncio.gather(*tasks)
        done, failed = sum(results), len(results) - sum(results)

        await jobs.update_one({"_id": oid}, {"$inc": {"done": done, "failed": failed}})
        for ident, ok in zip(idents, results):
            if ok:
                ok_rows.append(ident)

        fresh = await jobs.find_one({"_id": oid})
        if fresh.get("progress_msg_id"):
            notify.edit(fresh["tg_id"], fresh["progress_msg_id"], _text(fresh))

    if ok_rows:
        txt, pdf = pdfgen.build(ok_rows, job["site_slug"], job_id)
        notify.send_document(job["tg_id"], pdf, caption=f"{job['site_slug']} · {len(ok_rows)} accounts")
        notify.send_document(job["tg_id"], txt)

    await jobs.update_one({"_id": oid}, {"$set": {"status": "done", "finished_at": now()}})