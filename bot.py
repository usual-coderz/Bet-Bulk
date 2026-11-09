import asyncio
import importlib
import logging
import signal
from pathlib import Path

log = logging.getLogger("bot")

_UNSHADOWED: str | None = None


def _unshadow_queue() -> str | None:
    """queue.py naam stdlib ko shadow karta hai. Import se pehle hatao."""
    stray = Path(__file__).resolve().parent / "queue.py"
    if not stray.exists():
        return None

    target = stray.with_name("queue_shadowed.py")
    n = 1
    while target.exists():
        target = stray.with_name(f"queue_shadowed_{n}.py")
        n += 1

    try:
        stray.rename(target)
    except OSError as e:
        return f"rename fail ({e}) — queue.py abhi bhi stdlib shadow kar raha hai"
    importlib.invalidate_caches()
    return target.name


_UNSHADOWED = _unshadow_queue()

# ---- project imports: sirf unshadow ke baad ----
from aiogram import Bot, Dispatcher, Router  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.filters import Command, CommandStart, StateFilter  # noqa: E402
from aiogram.filters.callback_data import CallbackData  # noqa: E402
from aiogram.fsm.context import FSMContext  # noqa: E402
from aiogram.fsm.state import State, StatesGroup  # noqa: E402
from aiogram.types import CallbackQuery, Message  # noqa: E402
from aiogram.utils.keyboard import InlineKeyboardBuilder  # noqa: E402

import jobqueue  # noqa: E402
import logging_conf  # noqa: E402
import runner  # noqa: E402
import selftest  # noqa: E402
from config import settings  # noqa: E402
from db import (  # noqa: E402
    DuplicateKeyError, close, init_indexes, invite_codes, jobs, ping, sites,
)
from httpx_compat import describe as httpx_describe  # noqa: E402
from proxies import maintain, refresh, size  # noqa: E402
from schemas import job_doc  # noqa: E402
from sites.registry import build  # noqa: E402

router = Router()


class Form(StatesGroup):
    invite = State()
    count = State()
    schedule = State()


class SiteCB(CallbackData, prefix="site"):
    slug: str


class CountCB(CallbackData, prefix="cnt"):
    n: int


class SchedCB(CallbackData, prefix="sch"):
    minutes: int


def _admin(uid: int) -> bool:
    return uid in settings.admins


def sites_kb(rows):
    kb = InlineKeyboardBuilder()
    for s in rows:
        kb.button(text=s["name"], callback_data=SiteCB(slug=s["slug"]).pack())
    kb.adjust(2)
    return kb.as_markup()


def counts_kb(maxn: int):
    kb = InlineKeyboardBuilder()
    for n in (1, 5, 6, 10, 25):
        if n <= maxn:
            kb.button(text=str(n), callback_data=CountCB(n=n).pack())
    kb.adjust(5)
    return kb.as_markup()


def sched_kb():
    kb = InlineKeyboardBuilder()
    for label, m in (("Instant", 0), ("10 min", 10), ("30 min", 30), ("1 hour", 60)):
        kb.button(text=label, callback_data=SchedCB(minutes=m).pack())
    kb.adjust(2)
    return kb.as_markup()


async def _safe_edit(cb: CallbackQuery, text: str, kb=None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        log.debug("edit_text fail, naya message", exc_info=True)
        await cb.message.answer(text, reply_markup=kb)


# ---------- user flow ----------

@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    log.info("/start user=%d", m.from_user.id)

    rows = [s async for s in sites.find({"enabled": True})]
    if not rows:
        log.error("koi enabled site nahi mili")
        return await m.answer("Koi site enabled nahi hai. Pehle seed.py chalao.")

    await m.answer("Site chuno:", reply_markup=sites_kb(rows))


@router.callback_query(SiteCB.filter())
async def choose_site(cb: CallbackQuery, callback_data: SiteCB, state: FSMContext):
    site = await sites.find_one({"slug": callback_data.slug, "enabled": True})
    if not site:
        log.warning("site unavailable slug=%s", callback_data.slug)
        return await cb.answer("Unavailable", show_alert=True)

    await state.update_data(site_slug=site["slug"], site_name=site["name"])
    await state.set_state(Form.invite)
    await _safe_edit(cb, f"<b>{site['name']}</b>\nInvitation code bhejo:")
    await cb.answer()


@router.message(Form.invite)
async def take_invite(m: Message, state: FSMContext):
    code = (m.text or "").strip()
    d = await state.get_data()
    site = await sites.find_one({"slug": d.get("site_slug")})

    if not site:
        log.error("invite step me site gayab slug=%s", d.get("site_slug"))
        await state.clear()
        return await m.answer("Site gayab ho gayi. /start")

    log.info("invite user=%d site=%s code=%s", m.from_user.id, site["slug"], code)

    if not await build(site).validate_invite(code):
        log.warning("invite invalid site=%s code=%s", site["slug"], code)
        return await m.answer("Code invalid lag raha hai. Dobara bhejo.")

    await state.update_data(invite_code=code)
    await state.set_state(Form.count)
    await m.answer("Kitne accounts?", reply_markup=counts_kb(settings.max_accounts_per_job))


@router.callback_query(CountCB.filter(), StateFilter(Form.count))
async def take_count(cb: CallbackQuery, callback_data: CountCB, state: FSMContext):
    log.info("count user=%d n=%d", cb.from_user.id, callback_data.n)
    await state.update_data(count=callback_data.n)
    await state.set_state(Form.schedule)
    await _safe_edit(cb, "Gap chuno:", sched_kb())
    await cb.answer()


@router.callback_query(SchedCB.filter(), StateFilter(Form.schedule))
async def confirm(cb: CallbackQuery, callback_data: SchedCB, state: FSMContext):
    d = await state.get_data()

    if not d.get("site_slug") or not d.get("invite_code") or not d.get("count"):
        log.warning("confirm step me state adhura user=%d data=%s",
                    cb.from_user.id, sorted(d))
        await state.clear()
        await cb.answer("State gayab, /start se dobara", show_alert=True)
        return

    try:
        await invite_codes.update_one(
            {"site_slug": d["site_slug"], "code": d["invite_code"]},
            {"$setOnInsert": {"bound_tg_id": cb.from_user.id, "used": False}},
            upsert=True,
        )
    except DuplicateKeyError:
        log.debug("invite code already bound code=%s", d["invite_code"])

    res = await jobs.insert_one(job_doc(
        cb.from_user.id, d["site_slug"], d["invite_code"],
        d["count"], callback_data.minutes * 60))

    await _safe_edit(
        cb,
        f"<b>{d['site_name']}</b>\nqueued {d['count']} · gap {callback_data.minutes} min\n"
        f"<code>{res.inserted_id}</code>")

    await jobs.update_one({"_id": res.inserted_id},
                          {"$set": {"progress_msg_id": cb.message.message_id}})

    await jobqueue.q.put(str(res.inserted_id))

    log.info("QUEUED job=%s user=%d site=%s n=%d gap=%d pool=%d",
             res.inserted_id, cb.from_user.id, d["site_slug"],
             d["count"], callback_data.minutes, size())

    await state.clear()
    await cb.answer("Queued")


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    log.info("cancel user=%d", m.from_user.id)
    await state.clear()
    await m.answer("Cancel.")


@router.message(Command("jobs"))
async def my_jobs(m: Message):
    rows = []
    async for j in jobs.find({"tg_id": m.from_user.id}).sort("created_at", -1).limit(5):
        rows.append(f"<code>{j['_id']}</code> {j['site_slug']} {j['status']} "
                    f"{j['done']}/{j['count']}")
    await m.answer("\n".join(rows) or "koi job nahi")


# ---------- admin ----------

@router.message(Command("logs"))
async def logs_cmd(m: Message):
    if not _admin(m.from_user.id):
        return
    parts = (m.text or "").split()
    n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 80
    chunk = logging_conf.tail(min(n, 200))
    for i in range(0, len(chunk), 3900):
        await m.answer(f"<pre>{chunk[i:i + 3900]}</pre>")


@router.message(Command("diag"))
async def diag(m: Message):
    if not _admin(m.from_user.id):
        return

    from playwright.async_api import async_playwright

    lines = [
        f"httpx: {httpx_describe()}",
        f"proxy_mode: {settings.proxy_mode}",
        f"proxy pool: {size()}",
        f"queue: {jobqueue.q.qsize()}",
        f"inflight: {len(jobqueue._inflight)}",
        f"unshadowed: {_UNSHADOWED or '-'}",
    ]

    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            lines.append(f"chromium: OK {b.version}")
            await b.close()
    except Exception as e:
        lines.append(f"chromium: FAIL {type(e).__name__}")

    try:
        await ping()
        lines.append("mongo: OK")
    except Exception as e:
        lines.append(f"mongo: FAIL {type(e).__name__}")

    lines.append(f"running: {await jobs.count_documents({'status': 'running'})}")
    lines.append(f"queued: {await jobs.count_documents({'status': 'queued'})}")
    await m.answer("\n".join(lines))


@router.message(Command("refreshproxy"))
async def refresh_proxy(m: Message):
    if not _admin(m.from_user.id):
        return
    await m.answer("refresh chalu...")
    try:
        n = await refresh(force=True)
        log.info("manual proxy refresh -> %d", n)
        await m.answer(f"pool ab: {n}")
    except Exception as e:
        log.exception("manual refresh fail")
        await m.answer(f"fail: {type(e).__name__}")


@router.message(Command("sites"))
async def list_sites(m: Message):
    if not _admin(m.from_user.id):
        return
    rows = [f"{s['slug']} enabled={s['enabled']} pad={s.get('pad_right', 0)}"
            async for s in sites.find({})]
    await m.answer("\n".join(rows) or "khaali")


# ---------- boot ----------

async def _watch_stop(dp: Dispatcher, stop: asyncio.Event, bot: Bot) -> None:
    await stop.wait()
    log.info("stop signal mila, polling band")
    await dp.stop_polling()


async def main() -> None:
    logging_conf.setup()
    log.info("=== BOOT ===")

    if _UNSHADOWED:
        log.warning("queue.py shadow tha — %s pe rename kiya", _UNSHADOWED)
        if "fail" in _UNSHADOWED:
            log.error("rename fail — stdlib queue phir bhi shadow ho sakta hai")

    log.info("db=%s workers=%d batch=%d per_site=%d headless=%s",
             settings.mongo_db, settings.job_workers, settings.batch,
             settings.per_site, settings.headless)
    log.info("httpx=%s proxy_mode=%s", httpx_describe(), settings.proxy_mode)

    await selftest.run()
    await init_indexes()

    requeued = 0
    async for j in jobs.find({"status": {"$in": ["queued", "running"]}}):
        await jobs.update_one({"_id": j["_id"]}, {"$set": {"status": "queued"}})
        await jobqueue.q.put(str(j["_id"]))
        requeued += 1
    log.info("requeued %d stuck jobs", requeued)

    stop = asyncio.Event()
    asyncio.create_task(maintain(stop))
    jobqueue.start(runner.run_job, settings.job_workers)

    bot = Bot(settings.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    watcher = asyncio.create_task(_watch_stop(dp, stop, bot))

    try:
        await dp.start_polling(bot)
    finally:
        log.info("shutdown shuru")
        stop.set()
        watcher.cancel()
        await jobqueue.stop()
        await close()
        await bot.session.close()
        log.info("=== BYE ===")


if __name__ == "__main__":
    asyncio.run(main())