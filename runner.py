import asyncio
import logging
import secrets
import time

from bson import ObjectId

import crypto
import notify
import pdfgen
from config import settings
from db import credentials, jobs, sites
from identity import mobile, password, username
from proxies import mark_dead, pick, size
from schemas import cred_doc, now
from sites.base import RegisterError
from sites.registry import build

log = logging.getLogger("runner")

_sem: dict[str, asyncio.Semaphore] = {}
_heartbeats: dict[str, asyncio.Task] = {}


def _text(job: dict, elapsed: int) -> str:
    return (
        f"<b>{job['site_slug']}</b>\n"
        f"done {job['done']} / {job['count']} · failed {job['failed']}\n"
        f"{elapsed}s"
    )


async def _heartbeat(oid: ObjectId, started: float) -> None:
    while True:
        await asyncio.sleep(20)
        try:
            job = await jobs.find_one({"_id": oid})
            if not job or job["status"] != "running":
                return
            if job.get("progress_msg_id"):
                notify.edit(job["tg_id"], job["progress_msg_id"],
                            _text(job, int(time.time() - started)))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("heartbeat fail", exc_info=True)


def _acquire_proxy(tag: str, attempt: int) -> str | None:
    proxy = pick()

    if proxy:
        log.info("%s attempt=%d proxy=%s", tag, attempt, proxy)
        return proxy

    if settings.proxy_mode == "off":
        log.info("%s attempt=%d DIRECT (mode=off)", tag, attempt)
    else:
        log.warning("%s attempt=%d DIRECT (pool khaali, size=%d)", tag, attempt, size())

    return None


async def _one(job_id: str, site: dict, ident: dict, idx: int) -> bool:
    adapter = build(site)
    sem = _sem.setdefault(site["slug"], asyncio.Semaphore(settings.per_site))
    tag = f"job={job_id[:8]} #{idx} {ident['username']}"
    err = "unknown"

    for attempt in range(1, 4):
        proxy = _acquire_proxy(tag, attempt)

        async with sem:
            try:
                await adapter.register(ident, proxy)
                log.info("%s SUCCESS", tag)
                await credentials.insert_one(cred_doc(
                    job_id, site["slug"], ident["username"],
                    crypto.enc(ident["password"]), ident["mobile"]))
                return True
            except RegisterError as e:
                err = str(e)
                log.warning("%s fail: %s", tag, err)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                log.exception("%s unexpected error", tag)
            finally:
                if proxy:
                    mark_dead(proxy)

        await asyncio.sleep(3 + attempt * 4)

    log.error("%s FAILED 3 attempts: %s", tag, err)
    await credentials.insert_one(cred_doc(
        job_id, site["slug"], ident["username"],
        crypto.enc(ident["password"]), ident["mobile"],
        status="failed", error=err))
    return False


def _new_idents(job: dict, count: int) -> list[dict]:
    return [{
        "username": username(),
        "password": password(),
        "mobile": mobile(),
        "invite_code": job["invite_code"],
    } for _ in range(count)]


async def run_job(job_id: str) -> None:
    oid = ObjectId(job_id)

    job = await jobs.find_one_and_update(
        {"_id": oid, "status": "queued"},
        {"$set": {"status": "running", "claimed_at": now()}},
    )
    if not job:
        log.warning("job=%s claim fail (status badal gaya)", job_id)
        return

    started = time.time()
    log.info("job=%s START site=%s count=%d code=%s proxy_pool=%d",
             job_id, job["site_slug"], job["count"], job["invite_code"], size())

    site = await sites.find_one({"slug": job["site_slug"], "enabled": True})
    if not site:
        log.error("job=%s site missing/disabled: %s", job_id, job["site_slug"])
        await jobs.update_one({"_id": oid}, {"$set": {
            "status": "failed", "error": "site missing", "finished_at": now()}})
        notify.send(job["tg_id"], "Site config missing hai.")
        return

    if job.get("progress_msg_id"):
        notify.edit(job["tg_id"], job["progress_msg_id"], _text(job, 0))

    _heartbeats[job_id] = asyncio.create_task(_heartbeat(oid, started))

    ok_rows: list[dict] = []

    try:
        for start in range(0, job["count"], settings.batch):
            chunk = min(settings.batch, job["count"] - start)
            log.info("job=%s wave start=%d size=%d", job_id, start, chunk)

            idents = _new_idents(job, chunk)
            tasks = []

            for i, ident in enumerate(idents):
                tasks.append(asyncio.create_task(_one(job_id, site, ident, start + i + 1)))
                await asyncio.sleep(secrets.randint(5, 10))

            results = await asyncio.gather(*tasks)
            done, failed = sum(results), len(results) - sum(results)
            log.info("job=%s wave done ok=%d fail=%d", job_id, done, failed)

            await jobs.update_one({"_id": oid}, {"$inc": {"done": done, "failed": failed}})
            ok_rows.extend(i for i, ok in zip(idents, results) if ok)

            fresh = await jobs.find_one({"_id": oid})
            if fresh and fresh.get("progress_msg_id"):
                notify.edit(fresh["tg_id"], fresh["progress_msg_id"],
                            _text(fresh, int(time.time() - started)))

        if ok_rows:
            log.info("job=%s report bana rahe (%d ok)", job_id, len(ok_rows))
            txt, pdf = pdfgen.build(ok_rows, job["site_slug"], job_id)
            notify.send_document(job["tg_id"], pdf,
                                 caption=f"{job['site_slug']} · {len(ok_rows)} accounts")
            notify.send_document(job["tg_id"], txt)
            log.info("job=%s report bhej diya", job_id)
        else:
            notify.send(job["tg_id"],
                        f"<b>{job['site_slug']}</b>\n0 accounts bane. /logs dekh lo.")
            log.warning("job=%s zero success", job_id)

        await jobs.update_one({"_id": oid}, {"$set": {
            "status": "done", "finished_at": now()}})
        log.info("job=%s DONE ok=%d fail=%d elapsed=%ds",
                 job_id, len(ok_rows), job["count"] - len(ok_rows),
                 int(time.time() - started))

    except Exception as e:
        log.exception("job=%s crash", job_id)
        await jobs.update_one({"_id": oid}, {"$set": {
            "status": "failed", "error": str(e)[:300], "finished_at": now()}})
        notify.send(job["tg_id"], f"Job crash: <code>{type(e).__name__}</code>")
        raise
    finally:
        hb = _heartbeats.pop(job_id, None)
        if hb:
            hb.cancel()