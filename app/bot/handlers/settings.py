import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery

from app.bot.keyboards.schedule import timezone_menu
from app.bot.keyboards.settings import settings_menu
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.scheduler import reschedule_user
from app.db import queries
from app.db.database import async_session


router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "settings:show")
async def settings_screen(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await safe_edit_message(callback.message, "⚙️ Настройки", reply_markup=settings_menu(user.silent_notifications))


@router.callback_query(F.data == "settings:timezone")
async def settings_timezone(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(callback.message, "Выберите ваш город или ближайший часовой пояс:", reply_markup=timezone_menu("settings"))


@router.callback_query(F.data.startswith("tz:settings:"))
async def save_settings_timezone(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Сохранено")
    zone = callback.data.removeprefix("tz:settings:")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.save_timezone(session, user, zone)
        await reschedule_user(user.telegram_id)
        silent = user.silent_notifications
    await safe_edit_message(callback.message, "⚙️ Настройки\n\nЧасовой пояс обновлен.", reply_markup=settings_menu(silent))


@router.callback_query(F.data == "settings:silent")
async def toggle_silent(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Настройка сохранена")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        old_value = user.silent_notifications
        value = await queries.toggle_silent(session, user)
    logger.info(
        "Silent notifications toggled for user=%s old=%s new=%s message_id=%s",
        callback.from_user.id,
        old_value,
        value,
        callback.message.message_id if callback.message else None,
    )
    try:
        if callback.message is None:
            logger.error("Cannot update silent notifications keyboard: callback.message is None for user=%s", callback.from_user.id)
            return
        await callback.message.edit_reply_markup(reply_markup=settings_menu(value))
        logger.debug(
            "Silent notifications keyboard updated for user=%s new=%s",
            callback.from_user.id,
            value,
        )
    except TelegramBadRequest as exc:
        logger.exception(
            "Failed to update silent notifications keyboard for user=%s new=%s: %s",
            callback.from_user.id,
            value,
            exc,
        )
    except TelegramNetworkError as exc:
        logger.exception(
            "Network error while updating silent notifications keyboard for user=%s new=%s: %s",
            callback.from_user.id,
            value,
            exc,
        )
    except Exception as exc:
        logger.exception(
            "Unexpected error while updating silent notifications keyboard for user=%s new=%s: %s",
            callback.from_user.id,
            value,
            exc,
        )
