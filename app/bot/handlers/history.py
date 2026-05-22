from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.digest import history_long_digest
from app.bot.keyboards.history import history_digest, history_list
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.digest_delivery import HISTORY_LONG_DIGEST_TEXT, ensure_digest_html, is_digest_too_long, public_digest_url
from app.db import queries
from app.db.database import async_session


router = Router()


@router.callback_query(F.data.startswith("history:"))
async def history_router(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    parts = callback.data.split(":")
    if len(parts) == 2 and parts[1].isdigit():
        await show_history(callback, int(parts[1]))
        return
    if len(parts) == 4 and parts[1] == "view":
        await view_digest(callback, int(parts[2]), int(parts[3]))
        return
    if len(parts) == 4 and parts[1] == "parts":
        await view_digest_parts(callback, int(parts[2]), int(parts[3]))


async def show_history(callback: CallbackQuery, page: int) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        items, total = await queries.history_page(session, user.id, page)
    text = (
        "📚 История дайджестов\n\n"
        "Здесь хранятся ваши ранее сформированные дайджесты.\n\n"
        "⭐ Звездочкой отмечены дайджесты, добавленные в избранное."
    )
    if total == 0:
        text += "\n\nИстория пока пустая."
    await safe_edit_message(callback.message, text, reply_markup=history_list(items, page, total))


async def view_digest(callback: CallbackQuery, digest_id: int, page: int) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if digest and is_digest_too_long(digest.digest_text):
            token, _ = await ensure_digest_html(session, digest)
        else:
            token = None
    if not digest:
        await callback.message.answer("Дайджест не найден.")
        return
    if token:
        await safe_edit_message(
            callback.message,
            HISTORY_LONG_DIGEST_TEXT,
            reply_markup=history_long_digest(digest.id, page, digest.is_favorite, public_digest_url(token)),
        )
        return
    await safe_edit_message(
        callback.message,
        digest.digest_text,
        reply_markup=history_digest(digest.id, page, digest.is_favorite),
        parse_mode="HTML",
    )


async def view_digest_parts(callback: CallbackQuery, digest_id: int, page: int) -> None:
    from app.bot.handlers.digest import _send_digest_parts

    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
    if not digest:
        await callback.message.answer("Дайджест не найден.")
        return
    await _send_digest_parts(callback.message, digest, history_page=page)


@router.callback_query(F.data.startswith("fav:history:"))
async def toggle_history_favorite(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, digest_id, page = callback.data.split(":")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, int(digest_id), user.id)
        if not digest:
            await callback.message.answer("Дайджест не найден.")
            return
        await queries.set_favorite(session, digest, not digest.is_favorite)
        if is_digest_too_long(digest.digest_text):
            token, _ = await ensure_digest_html(session, digest)
            markup = history_long_digest(digest.id, int(page), digest.is_favorite, public_digest_url(token))
        else:
            markup = history_digest(digest.id, int(page), digest.is_favorite)
        await callback.message.edit_reply_markup(reply_markup=markup)
