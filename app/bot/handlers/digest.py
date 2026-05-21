from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.digest import digest_actions, digest_mode, digest_period, refresh_confirm
from app.core.digest import build_digest, refresh_digest
from app.db import queries
from app.db.database import async_session


router = Router()


@router.callback_query(F.data == "digest:start")
async def choose_digest_mode(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Как сформировать дайджест?", reply_markup=digest_mode())
    await callback.answer()


@router.callback_query(F.data.startswith("digest:mode:"))
async def choose_period(callback: CallbackQuery) -> None:
    mode = callback.data.split(":")[2]
    if mode == "selected_sources":
        async with async_session() as session:
            user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
            selected = await queries.selected_sources(session, user.id)
        if not selected:
            await callback.message.edit_text(
                "У вас пока нет выбранных источников. Сначала выберите источники для дайджеста.",
                reply_markup=await __import__("app.bot.handlers.sources", fromlist=["_categories_keyboard"])._categories_keyboard("digest"),
            )
            await callback.answer()
            return
    await callback.message.edit_text("За какой период подготовить дайджест?", reply_markup=digest_period(mode))
    await callback.answer()


@router.callback_query(F.data.startswith("digest:period:"))
async def generate_digest(callback: CallbackQuery) -> None:
    _, _, mode, period = callback.data.split(":")
    await callback.message.edit_text("Готовлю дайджест: читаю RSS и собираю главное...")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await build_digest(session, user, mode, period)
        await callback.message.answer(
            digest.digest_text,
            reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite),
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("fav:fresh:"))
async def toggle_fresh_favorite(callback: CallbackQuery) -> None:
    digest_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await callback.answer("Дайджест не найден", show_alert=True)
            return
        await queries.set_favorite(session, digest, not digest.is_favorite)
        await callback.message.edit_reply_markup(reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite))
        await callback.answer("Добавлено в избранное" if digest.is_favorite else "Удалено из избранного")


@router.callback_query(F.data.startswith("fb:"))
async def feedback(callback: CallbackQuery) -> None:
    _, digest_id, value = callback.data.split(":")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, int(digest_id), user.id)
        if digest:
            await queries.set_feedback(session, digest, value)
    await callback.answer("Спасибо за вашу оценку")


@router.callback_query(F.data.startswith("refresh:empty:"))
async def refresh_empty(callback: CallbackQuery) -> None:
    await callback.answer("Попытки обновления для этого дайджеста закончились", show_alert=True)


@router.callback_query(F.data.startswith("refresh:ask:"))
async def ask_refresh(callback: CallbackQuery) -> None:
    digest_id = int(callback.data.split(":")[2])
    await callback.message.answer(
        "Вы уверены, что хотите проверить новые новости?\n"
        "Это действие использует одну попытку обновления для текущего дайджеста.",
        reply_markup=refresh_confirm(digest_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("refresh:no:"))
async def cancel_refresh(callback: CallbackQuery) -> None:
    digest_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if digest:
            await callback.message.edit_text(
                "Проверка отменена. Текущий дайджест остается без изменений.",
                reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite),
            )
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("refresh:yes:"))
async def confirm_refresh(callback: CallbackQuery) -> None:
    digest_id = int(callback.data.split(":")[2])
    await callback.message.edit_text("Проверяю RSS-источники...")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await callback.answer("Дайджест не найден", show_alert=True)
            return
        if digest.refresh_attempts_left <= 0:
            await callback.answer("Попытки закончились", show_alert=True)
            return
        await queries.decrement_refresh(session, digest)
        new_digest = await refresh_digest(session, user, digest)
        if not new_digest:
            await callback.message.answer("Новых новостей пока нет. Текущий дайджест остается актуальным.")
        else:
            await callback.message.answer(
                new_digest.digest_text,
                reply_markup=digest_actions(new_digest.id, new_digest.refresh_attempts_left, new_digest.is_favorite),
                disable_web_page_preview=True,
            )
    await callback.answer()
