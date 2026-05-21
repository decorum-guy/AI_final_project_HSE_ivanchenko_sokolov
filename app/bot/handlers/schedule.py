from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.schedule import WEEKDAYS, schedule_menu, schedule_times, schedule_weekdays, timezone_menu, weekly_schedule_times
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.scheduler import reschedule_user
from app.db import queries
from app.db.database import async_session


router = Router()
PENDING_SCHEDULE: dict[int, tuple[str, str, str | None]] = {}

SCHEDULE_TITLES = {
    "morning": "каждое утро",
    "evening": "каждый вечер",
    "weekly": "каждый понедельник",
}
WEEKDAY_TITLES = {value: title.lower() for title, value in WEEKDAYS}


def _schedule_setting_text(user) -> str:
    if not user.schedule_enabled or not user.schedule_type or not user.schedule_time:
        return "отключено"

    title = SCHEDULE_TITLES.get(user.schedule_type, user.schedule_type)
    if user.schedule_type == "weekly" and user.schedule_day:
        title = f"каждый {WEEKDAY_TITLES.get(user.schedule_day, user.schedule_day)}"
    timezone = f", {user.timezone}" if user.timezone else ""
    return f"{title} в {user.schedule_time}{timezone}"


def _schedule_screen_text(user, prefix: str | None = None) -> str:
    lines = []
    if prefix:
        lines.extend([prefix, ""])
    lines.append("Когда присылать дайджест?")
    lines.append(f"Текущая настройка: {_schedule_setting_text(user)}")
    return "\n".join(lines)


@router.callback_query(F.data == "schedule:show")
async def schedule_screen(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await safe_edit_message(callback.message, _schedule_screen_text(user), reply_markup=schedule_menu())


@router.callback_query(F.data.startswith("schedule:type:"))
async def choose_time(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    schedule_type = callback.data.split(":")[2]
    if schedule_type == "weekly":
        await safe_edit_message(callback.message, "Выберите день еженедельного дайджеста:", reply_markup=schedule_weekdays())
        return
    title = {
        "morning": "Выберите время утреннего дайджеста:",
        "evening": "Выберите время вечернего дайджеста:",
    }[schedule_type]
    await safe_edit_message(callback.message, title, reply_markup=schedule_times(schedule_type))


@router.callback_query(F.data.startswith("schedule:weekday:"))
async def choose_weekly_time(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    day = callback.data.split(":")[2]
    await safe_edit_message(callback.message, "Выберите время еженедельного дайджеста:", reply_markup=weekly_schedule_times(day))


@router.callback_query(F.data.startswith("schedule:time:"))
async def save_time(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    parts = callback.data.split(":")
    schedule_type = parts[2]
    schedule_day = parts[3] if schedule_type == "weekly" and len(parts) == 5 else None
    schedule_time = parts[4] if schedule_type == "weekly" and len(parts) == 5 else parts[3]
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        if not user.timezone:
            PENDING_SCHEDULE[user.telegram_id] = (schedule_type, schedule_time, schedule_day)
            await safe_edit_message(callback.message, "Выберите ваш город или ближайший часовой пояс:", reply_markup=timezone_menu("schedule"))
            return
        await queries.save_schedule(session, user, schedule_type, schedule_time, schedule_day)
        await session.refresh(user)
        await reschedule_user(user.telegram_id)
    await safe_edit_message(callback.message, _schedule_screen_text(user, "Расписание дайджестов сохранено."), reply_markup=schedule_menu())


@router.callback_query(F.data == "schedule:disable")
async def disable(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.disable_schedule(session, user)
        await session.refresh(user)
        await reschedule_user(user.telegram_id)
    await safe_edit_message(callback.message, _schedule_screen_text(user, "Рассылка дайджестов отключена."), reply_markup=schedule_menu())


@router.callback_query(F.data.startswith("tz:schedule:"))
async def schedule_timezone(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    zone = callback.data.removeprefix("tz:schedule:")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.save_timezone(session, user, zone)
        pending = PENDING_SCHEDULE.pop(user.telegram_id, None)
        if pending:
            await queries.save_schedule(session, user, pending[0], pending[1], pending[2] if len(pending) > 2 else None)
        await session.refresh(user)
        await reschedule_user(user.telegram_id)
    await safe_edit_message(callback.message, _schedule_screen_text(user, "Часовой пояс и расписание сохранены."), reply_markup=schedule_menu())
