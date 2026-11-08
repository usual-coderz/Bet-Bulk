import asyncio

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import queue
import runner
from config import settings
from db import DuplicateKeyError, init_indexes, invite_codes, jobs, sites
from proxies import maintain, size
from schemas import job_doc
from sites.registry import build

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


def sites_kb(rows):
    kb = InlineKeyboardBuilder()
    for s in rows:
        kb.button(text=s["name"], callback_data=SiteCB(slug=s["slug"]).pack())
    kb.adjust(2)
    return kb.as_markup()


def counts_kb(maxn):
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
    rows = [s async for s in sites.find({"enabled": True})]
    if not rows:
        return await m.answer("Koi site enabled nahi hai.")
    await m.answer("Site chuno:", reply_markup=sites_kb(rows))


@router.message(Command("proxy"))
async def proxy_stat(m: Message):
    await m.answer(f"Live proxy pool: <b>{size()}</b>")


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

    if not await build(site).validate_invite(code):
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
            {"$setOnInsert": {"bound_tg_id": cb.from_user.id, "used": False}}, upsert=True)
    except DuplicateKeyError:
        pass

    res = await jobs.insert_one(job_doc(cb.from_user.id, d["site_slug"], d["invite_code"],
                                        d["count"], callback_data.minutes * 60))
    msg = await cb.message.edit_text(
        f"<b>{d['site_name']}</b>\nqueued {d['count']} accounts · gap {callback_data.minutes} min")
    await jobs.update_one({"_id": res.inserted_id}, {"$set": {"progress_msg_id": msg.message_id}})

    await queue.q.put(str(res.inserted_id))
    await state.clear()
    await cb.answer("Queued")


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Cancel ho gaya.")


async def main():
    await init_indexes()

    # bot restart pe atke hue jobs wapas queue me
    async for j in jobs.find({"status": {"$in": ["queued", "running"]}}):
        await jobs.update_one({"_id": j["_id"]}, {"$set": {"status": "queued"}})
        await queue.q.put(str(j["_id"]))

    stop = asyncio.Event()
    asyncio.create_task(maintain(stop, settings.proxy_refresh_sec))
    queue.start(runner.run_job, settings.job_workers)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())