from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.history import history_digest, history_list
from app.db import queries
from app.db.database import async_session


router = Router()


@router.callback_query(F.data.startswith("history:"))
async def history_router(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) == 2 and parts[1].isdigit():
        await show_history(callback, int(parts[1]))
        return
    if len(parts) == 4 and parts[1] == "view":
        await view_digest(callback, int(parts[2]), int(parts[3]))
        return


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
    await callback.message.edit_text(text, reply_markup=history_list(items, page, total), disable_web_page_preview=True)
    await callback.answer()


async def view_digest(callback: CallbackQuery, digest_id: int, page: int) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
    if not digest:
        await callback.answer("Дайджест не найден", show_alert=True)
        return
    await callback.message.edit_text(
        digest.digest_text,
        reply_markup=history_digest(digest.id, page, digest.is_favorite),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fav:history:"))
async def toggle_history_favorite(callback: CallbackQuery) -> None:
    _, _, digest_id, page = callback.data.split(":")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, int(digest_id), user.id)
        if not digest:
            await callback.answer("Дайджест не найден", show_alert=True)
            return
        await queries.set_favorite(session, digest, not digest.is_favorite)
        await callback.message.edit_reply_markup(reply_markup=history_digest(digest.id, int(page), digest.is_favorite))
        await callback.answer("Добавлено" if digest.is_favorite else "Удалено")

