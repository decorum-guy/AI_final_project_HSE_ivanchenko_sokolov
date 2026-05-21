import time

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.digest import digest_actions, digest_mode, digest_period, refresh_confirm
from app.bot.keyboards.interests import interests_menu, interests_need_sources
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.digest import build_digest, refresh_digest
from app.db import queries
from app.db.database import async_session


router = Router()


@router.callback_query(F.data == "digest:start")
async def choose_digest_mode(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(callback.message, "Как сформировать дайджест?", reply_markup=digest_mode())


@router.callback_query(F.data.startswith("digest:mode:"))
async def choose_period(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    mode = callback.data.split(":")[2]
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        selected = await queries.selected_sources(session, user.id)

    if mode == "interests":
        if not user.interests_text:
            await safe_edit_message(
                callback.message,
                "Сначала укажите интересы, чтобы я мог собрать персональный дайджест.",
                reply_markup=interests_menu(),
            )
            return
        if not selected:
            await safe_edit_message(
                callback.message,
                "У вас пока нет выбранных источников. Я могу подобрать их по вашим интересам.",
                reply_markup=interests_need_sources(),
            )
            return

    if mode == "selected_sources" and not selected:
        await safe_edit_message(
            callback.message,
            "У вас пока нет выбранных источников. Сначала выберите источники для дайджеста.",
            reply_markup=await __import__("app.bot.handlers.sources", fromlist=["_categories_keyboard"])._categories_keyboard("digest"),
        )
        return
    await safe_edit_message(callback.message, "За какой период подготовить дайджест?", reply_markup=digest_period(mode))


@router.callback_query(F.data.startswith("digest:period:"))
async def generate_digest(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, mode, period = callback.data.split(":")
    loading = await safe_edit_message(
        callback.message,
        "⏳ Собираю дайджест...\n\nПодготавливаю источники и свежие новости.",
    )
    target_message = loading or callback.message
    last_progress_at = 0.0

    async def progress(done: int, total: int, found: int) -> None:
        nonlocal last_progress_at
        now = time.monotonic()
        if done != total and now - last_progress_at < 1.5:
            return
        last_progress_at = now
        await safe_edit_message(
            target_message,
            f"⏳ Собираю дайджест...\n\nОбработано источников: {done} из {total}\nНайдено новостей: {found}",
        )

    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await build_digest(session, user, mode, period, progress_callback=progress)
        keyboard = digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)

    edited = await safe_edit_message(target_message, digest.digest_text, reply_markup=keyboard)
    if not edited:
        await callback.message.answer(digest.digest_text, reply_markup=keyboard, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("fav:fresh:"))
async def toggle_fresh_favorite(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    digest_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await safe_callback_answer(callback, "Дайджест не найден", show_alert=True)
            return
        await queries.set_favorite(session, digest, not digest.is_favorite)
        await callback.message.edit_reply_markup(reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite))


@router.callback_query(F.data.startswith("fb:"))
async def feedback(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Спасибо за вашу оценку")
    _, digest_id, value = callback.data.split(":")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, int(digest_id), user.id)
        if digest:
            await queries.set_feedback(session, digest, value)


@router.callback_query(F.data.startswith("refresh:empty:"))
async def refresh_empty(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Попытки обновления для этого дайджеста закончились", show_alert=True)


@router.callback_query(F.data.startswith("refresh:ask:"))
async def ask_refresh(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    digest_id = int(callback.data.split(":")[2])
    await callback.message.answer(
        "Вы уверены, что хотите проверить новые новости?\n"
        "Это действие использует одну попытку обновления для текущего дайджеста.",
        reply_markup=refresh_confirm(digest_id),
    )


@router.callback_query(F.data.startswith("refresh:no:"))
async def cancel_refresh(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Отменено")
    digest_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if digest:
            await safe_edit_message(
                callback.message,
                "Проверка отменена. Текущий дайджест остается без изменений.",
                reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite),
            )


@router.callback_query(F.data.startswith("refresh:yes:"))
async def confirm_refresh(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    digest_id = int(callback.data.split(":")[2])
    await safe_edit_message(callback.message, "Проверяю RSS-источники...")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await callback.message.answer("Дайджест не найден.")
            return
        if digest.refresh_attempts_left <= 0:
            await callback.message.answer("Попытки обновления для этого дайджеста закончились.")
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
