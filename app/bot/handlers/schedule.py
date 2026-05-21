from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.schedule import schedule_menu, schedule_times, timezone_menu
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.scheduler import reschedule_user
from app.db import queries
from app.db.database import async_session


router = Router()
PENDING_SCHEDULE: dict[int, tuple[str, str]] = {}


@router.callback_query(F.data == "schedule:show")
async def schedule_screen(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(callback.message, "Когда присылать дайджест?", reply_markup=schedule_menu())


@router.callback_query(F.data.startswith("schedule:type:"))
async def choose_time(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    schedule_type = callback.data.split(":")[2]
    title = {
        "morning": "Выберите время утреннего дайджеста:",
        "evening": "Выберите время вечернего дайджеста:",
        "weekly": "Выберите время еженедельного дайджеста:",
    }[schedule_type]
    await safe_edit_message(callback.message, title, reply_markup=schedule_times(schedule_type))


@router.callback_query(F.data.startswith("schedule:time:"))
async def save_time(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, schedule_type, schedule_time = callback.data.split(":", 3)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        if not user.timezone:
            PENDING_SCHEDULE[user.telegram_id] = (schedule_type, schedule_time)
            await safe_edit_message(callback.message, "Выберите ваш город или ближайший часовой пояс:", reply_markup=timezone_menu("schedule"))
            return
        await queries.save_schedule(session, user, schedule_type, schedule_time)
        await reschedule_user(user.telegram_id)
    await safe_edit_message(callback.message, "Расписание дайджестов сохранено.", reply_markup=schedule_menu())


@router.callback_query(F.data == "schedule:disable")
async def disable(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.disable_schedule(session, user)
        await reschedule_user(user.telegram_id)
    await safe_edit_message(callback.message, "Рассылка дайджестов отключена.", reply_markup=schedule_menu())


@router.callback_query(F.data.startswith("tz:schedule:"))
async def schedule_timezone(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    zone = callback.data.removeprefix("tz:schedule:")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.save_timezone(session, user, zone)
        pending = PENDING_SCHEDULE.pop(user.telegram_id, None)
        if pending:
            await queries.save_schedule(session, user, pending[0], pending[1])
        await reschedule_user(user.telegram_id)
    await safe_edit_message(callback.message, "Часовой пояс и расписание сохранены.", reply_markup=schedule_menu())
