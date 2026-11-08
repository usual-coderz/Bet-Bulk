import asyncio

q: asyncio.Queue[str] = asyncio.Queue()
_workers: list[asyncio.Task] = []


async def _loop(handler):
    while True:
        job_id = await q.get()
        try:
            await handler(job_id)
        except Exception:
            pass
        finally:
            q.task_done()


def start(handler, n: int):
    for _ in range(n):
        _workers.append(asyncio.create_task(_loop(handler)))


async def stop():
    for w in _workers:
        w.cancel()