import asyncio
import logging

from bson import ObjectId

from db import jobs
from notify import alert_admins
from schemas import now

log = logging.getLogger("queue")

q: asyncio.Queue[str] = asyncio.Queue()
_workers: list[asyncio.Task] = []


async def _loop(handler) -> None:
    log.info("worker up")
    while True:
        job_id = await q.get()
        log.info("picked job=%s depth=%d", job_id, q.qsize())
        try:
            await handler(job_id)
            log.info("job finished job=%s", job_id)
        except asyncio.CancelledError:
            log.warning("worker cancelled job=%s", job_id)
            raise
        except Exception:
            log.exception("job CRASH job=%s", job_id)
            try:
                await jobs.update_one(
                    {"_id": ObjectId(job_id)},
                    {"$set": {"status": "failed", "error": "worker crash", "finished_at": now()}},
                )
            except Exception:
                log.exception("mark failed bhi fail job=%s", job_id)
            alert_admins(f"job crash: <code>{job_id}</code>")
        finally:
            q.task_done()


def start(handler, n: int) -> None:
    for _ in range(max(1, n)):
        _workers.append(asyncio.create_task(_loop(handler)))
    log.info("%d worker start", len(_workers))


async def stop() -> None:
    for w in _workers:
        w.cancel()
    await asyncio.gather(*_workers, return_exceptions=True)
    log.info("workers band")