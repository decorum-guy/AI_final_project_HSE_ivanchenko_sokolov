from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.schedule import timezone_menu
from app.bot.keyboards.settings import settings_menu
from app.core.scheduler import reschedule_user
from app.db import queries
from app.db.database import async_session


router = Router()


@router.callback_query(F.data == "settings:show")
async def settings_screen(callback: CallbackQuery) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await callback.message.edit_text("⚙️ Настройки", reply_markup=settings_menu(user.silent_notifications))
    await callback.answer()


@router.callback_query(F.data == "settings:timezone")
async def settings_timezone(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Выберите ваш город или ближайший часовой пояс:", reply_markup=timezone_menu("settings"))
    await callback.answer()


@router.callback_query(F.data.startswith("tz:settings:"))
async def save_settings_timezone(callback: CallbackQuery) -> None:
    zone = callback.data.removeprefix("tz:settings:")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.save_timezone(session, user, zone)
        await reschedule_user(user.telegram_id)
        silent = user.silent_notifications
    await callback.message.edit_text("⚙️ Настройки\n\nЧасовой пояс обновлен.", reply_markup=settings_menu(silent))
    await callback.answer("Сохранено")


@router.callback_query(F.data == "settings:silent")
async def toggle_silent(callback: CallbackQuery) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        value = await queries.toggle_silent(session, user)
    await callback.message.edit_reply_markup(reply_markup=settings_menu(value))
    await callback.answer("Настройка сохранена")
