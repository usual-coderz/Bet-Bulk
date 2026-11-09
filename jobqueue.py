import asyncio
import logging
import time

from bson import ObjectId

from config import settings
from db import jobs
from notify import alert_admins
from schemas import now

log = logging.getLogger("queue")

JOB_TIMEOUT = 3600

q: asyncio.Queue[str] = asyncio.Queue()
_workers: list[asyncio.Task] = []
_inflight: set[str] = set()
_stopping = False


async def _fail(job_id: str, reason: str) -> None:
    try:
        await jobs.update_one(
            {"_id": ObjectId(job_id), "status": {"$in": ["running", "queued"]}},
            {"$set": {"status": "failed", "error": reason[:300], "finished_at": now()}},
        )
    except Exception:
        log.exception("mark failed bhi fail job=%s", job_id)


async def _loop(handler) -> None:
    log.info("worker up")
    while True:
        try:
            job_id = await asyncio.wait_for(q.get(), timeout=2.0)
        except asyncio.TimeoutError:
            if _stopping:
                log.info("worker band (drain complete)")
                return
            continue

        if job_id in _inflight:
            log.warning("job=%s already inflight, skip", job_id)
            q.task_done()
            continue

        _inflight.add(job_id)
        log.info("picked job=%s depth=%d", job_id, q.qsize())
        started = time.time()

        try:
            await asyncio.wait_for(handler(job_id), timeout=JOB_TIMEOUT)
            log.info("job finished job=%s elapsed=%ds", job_id, int(time.time() - started))

        except asyncio.TimeoutError:
            log.error("job=%s TIMEOUT %ds", job_id, JOB_TIMEOUT)
            await _fail(job_id, f"job timeout {JOB_TIMEOUT}s")
            alert_admins(f"job timeout: <code>{job_id}</code>")

        except asyncio.CancelledError:
            log.warning("worker cancelled job=%s", job_id)
            raise

        except Exception:
            log.exception("job CRASH job=%s", job_id)
            await _fail(job_id, "worker crash")
            alert_admins(f"job crash: <code>{job_id}</code>")

        finally:
            _inflight.discard(job_id)
            q.task_done()


def start(handler, n: int) -> None:
    global _stopping
    _stopping = False
    for _ in range(max(1, n)):
        _workers.append(asyncio.create_task(_loop(handler)))
    log.info("%d worker start", len(_workers))


async def stop() -> None:
    global _stopping
    _stopping = True
    log.info("drain shuru (inflight=%d queued=%d)", len(_inflight), q.qsize())

    deadline = time.monotonic() + 90
    while _inflight and time.monotonic() < deadline:
        await asyncio.sleep(1)

    if _inflight:
        log.warning("drain timeout, %d job abhi bhi chal rahe — cancel", len(_inflight))

    for w in _workers:
        w.cancel()
    await asyncio.gather(*_workers, return_exceptions=True)
    _workers.clear()
    log.info("workers band")