from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.schedule import schedule_menu, schedule_times, timezone_menu
from app.core.scheduler import reschedule_user
from app.db import queries
from app.db.database import async_session


router = Router()


PENDING_SCHEDULE: dict[int, tuple[str, str]] = {}


@router.callback_query(F.data == "schedule:show")
async def schedule_screen(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Когда присылать дайджест?", reply_markup=schedule_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("schedule:type:"))
async def choose_time(callback: CallbackQuery) -> None:
    schedule_type = callback.data.split(":")[2]
    title = {
        "morning": "Выберите время утреннего дайджеста:",
        "evening": "Выберите время вечернего дайджеста:",
        "weekly": "Выберите время еженедельного дайджеста:",
    }[schedule_type]
    await callback.message.edit_text(title, reply_markup=schedule_times(schedule_type))
    await callback.answer()


@router.callback_query(F.data.startswith("schedule:time:"))
async def save_time(callback: CallbackQuery) -> None:
    _, _, schedule_type, schedule_time = callback.data.split(":", 3)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        if not user.timezone:
            PENDING_SCHEDULE[user.telegram_id] = (schedule_type, schedule_time)
            await callback.message.edit_text("Выберите ваш город или ближайший часовой пояс:", reply_markup=timezone_menu("schedule"))
            await callback.answer()
            return
        await queries.save_schedule(session, user, schedule_type, schedule_time)
        await reschedule_user(user.telegram_id)
    await callback.message.edit_text("Расписание дайджестов сохранено.", reply_markup=schedule_menu())
    await callback.answer()


@router.callback_query(F.data == "schedule:disable")
async def disable(callback: CallbackQuery) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.disable_schedule(session, user)
        await reschedule_user(user.telegram_id)
    await callback.message.edit_text("Рассылка дайджестов отключена.", reply_markup=schedule_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("tz:schedule:"))
async def schedule_timezone(callback: CallbackQuery) -> None:
    zone = callback.data.removeprefix("tz:schedule:")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.save_timezone(session, user, zone)
        pending = PENDING_SCHEDULE.pop(user.telegram_id, None)
        if pending:
            await queries.save_schedule(session, user, pending[0], pending[1])
        await reschedule_user(user.telegram_id)
    await callback.message.edit_text("Часовой пояс и расписание сохранены.", reply_markup=schedule_menu())
    await callback.answer()
