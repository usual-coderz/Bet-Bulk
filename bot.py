import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import logging_conf
import queue
import runner
import selftest
from config import settings
from db import DuplicateKeyError, close, db, init_indexes, invite_codes, jobs, ping, sites
from proxies import maintain, size
from schemas import job_doc
from sites.registry import build

log = logging.getLogger("bot")
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


@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    log.info("/start user=%d", m.from_user.id)
    rows = [s async for s in sites.find({"enabled": True})]
    if not rows:
        return await m.answer("Koi site enabled nahi hai. Pehle seed.py chalao.")
    await m.answer("Site chuno:", reply_markup=sites_kb(rows))


@router.callback_query(SiteCB.filter())
async def choose_site(cb: CallbackQuery, callback_data: SiteCB, state: FSMContext):
    site = await sites.find_one({"slug": callback_data.slug, "enabled": True})
    if not site:
        return await cb.answer("Unavailable", show_alert=True)
    await state.update_data(site_slug=site["slug"], site_name=site["name"])
    await state.set_state(Form.invite)
    await cb.message.edit_text(f"<b>{site['name']}</b>\nInvitation code bhejo:")
    await cb.answer()


@router.message(Form.invite)
async def take_invite(m: Message, state: FSMContext):
    code = (m.text or "").strip()
    d = await state.get_data()
    site = await sites.find_one({"slug": d["site_slug"]})
    if not site:
        return await m.answer("Site gayab ho gayi. /start")

    log.info("invite user=%d site=%s code=%s", m.from_user.id, site["slug"], code)
    if not await build(site).validate_invite(code):
        log.warning("invite invalid code=%s", code)
        return await m.answer("Code invalid lag raha hai. Dobara bhejo.")

    await state.update_data(invite_code=code)
    await state.set_state(Form.count)
    await m.answer("Kitne accounts?", reply_markup=counts_kb(settings.max_accounts_per_job))


@router.callback_query(CountCB.filter(), StateFilter(Form.count))
async def take_count(cb: CallbackQuery, callback_data: CountCB, state: FSMContext):
    await state.update_data(count=callback_data.n)
    await state.set_state(Form.schedule)
    await cb.message.edit_text("Gap chuno:", reply_markup=sched_kb())
    await cb.answer()


@router.callback_query(SchedCB.filter(), StateFilter(Form.schedule))
async def confirm(cb: CallbackQuery, callback_data: SchedCB, state: FSMContext):
    d = await state.get_data()
    try:
        await invite_codes.update_one(
            {"site_slug": d["site_slug"], "code": d["invite_code"]},
            {"$setOnInsert": {"bound_tg_id": cb.from_user.id, "used": False}},
            upsert=True,
        )
    except DuplicateKeyError:
        pass

    res = await jobs.insert_one(job_doc(
        cb.from_user.id, d["site_slug"], d["invite_code"],
        d["count"], callback_data.minutes * 60))

    msg = await cb.message.edit_text(
        f"<b>{d['site_name']}</b>\nqueued {d['count']} · gap {callback_data.minutes} min\n"
        f"<code>{res.inserted_id}</code>")
    await jobs.update_one({"_id": res.inserted_id},
                          {"$set": {"progress_msg_id": msg.message_id}})

    await queue.q.put(str(res.inserted_id))
    log.info("QUEUED job=%s user=%d site=%s n=%d gap=%d",
             res.inserted_id, cb.from_user.id, d["site_slug"],
             d["count"], callback_data.minutes)
    await state.clear()
    await cb.answer("Queued")


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Cancel.")


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

    lines = [f"queue: {queue.q.qsize()}", f"proxies: {size()}"]

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
        lines.append(f"mongo: FAIL {e}")

    lines.append(f"running: {await jobs.count_documents({'status': 'running'})}")
    lines.append(f"queued: {await jobs.count_documents({'status': 'queued'})}")
    await m.answer("\n".join(lines))


@router.message(Command("sites"))
async def list_sites(m: Message):
    rows = [f"{s['slug']} enabled={s['enabled']}" async for s in sites.find({})]
    await m.answer("\n".join(rows) or "khaali")


async def main() -> None:
    logging_conf.setup()
    log.info("=== BOOT ===")
    log.info("db=%s workers=%d batch=%d per_site=%d headless=%s",
             settings.mongo_db, settings.job_workers, settings.batch,
             settings.per_site, settings.headless)

    await selftest.run()
    await init_indexes()

    requeued = 0
    async for j in jobs.find({"status": {"$in": ["queued", "running"]}}):
        await jobs.update_one({"_id": j["_id"]}, {"$set": {"status": "queued"}})
        await queue.q.put(str(j["_id"]))
        requeued += 1
    log.info("requeued %d stuck jobs", requeued)

    stop = asyncio.Event()
    asyncio.create_task(maintain(stop))
    queue.start(runner.run_job, settings.job_workers)

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

    try:
        await dp.start_polling(bot)
    finally:
        log.info("shutdown shuru")
        stop.set()
        await queue.stop()
        await close()
        await bot.session.close()
        log.info("=== BYE ===")


if __name__ == "__main__":
    asyncio.run(main())