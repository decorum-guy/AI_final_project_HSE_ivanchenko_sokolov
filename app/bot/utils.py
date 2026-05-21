import logging

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, Message


logger = logging.getLogger(__name__)


async def safe_callback_answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest as exc:
        error_text = str(exc)
        if "query is too old" in error_text or "query ID is invalid" in error_text:
            return
        raise
    except TelegramNetworkError as exc:
        logger.warning("Telegram callback answer timeout/network error: %s", exc)
        return


async def safe_edit_message(message: Message, text: str, reply_markup=None, disable_web_page_preview: bool = True):
    try:
        return await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return message
        logger.warning("Failed to edit message: %s", exc)
        return None
    except TelegramNetworkError as exc:
        logger.warning("Telegram edit timeout/network error: %s", exc)
        return None
