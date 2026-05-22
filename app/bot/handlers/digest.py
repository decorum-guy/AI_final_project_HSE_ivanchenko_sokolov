import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.digest import (
    digest_actions,
    digest_mode,
    digest_period,
    long_digest_options,
    refresh_confirm,
    too_many_sources_warning,
)
from app.bot.keyboards.history import history_digest
from app.bot.keyboards.interests import interests_need_sources, interests_need_topics
from app.bot.keyboards.main import main_menu, main_menu_text
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.digest import build_digest, refresh_digest
from app.core.digest_delivery import (
    LONG_DIGEST_TEXT,
    SAFE_TELEGRAM_LIMIT,
    SHORTEN_FAILED_TEXT,
    ensure_digest_html,
    is_digest_too_long,
    public_digest_url,
    split_digest_into_parts,
)
from app.core.gigachat_client import GigaChatDigestClient
from app.db import queries
from app.db.database import async_session


router = Router()
MANY_SOURCES_THRESHOLD = 8


def _shorten_attempts_left(digest) -> int:
    return digest.shorten_attempts_left if digest.shorten_attempts_left is not None else 2


async def _digest_html_url(digest) -> str:
    if digest.html_token and digest.html_path:
        return public_digest_url(digest.html_token)
    async with async_session() as session:
        fresh = await queries.get_digest(session, digest.id, digest.user_id)
        if not fresh:
            raise RuntimeError("Digest not found while creating HTML page")
        token, _ = await ensure_digest_html(session, fresh)
    return public_digest_url(token)


async def _show_digest_or_fallback(message: Message, digest, *, edit: bool = True) -> None:
    if is_digest_too_long(digest.digest_text):
        markup = long_digest_options(digest.id, _shorten_attempts_left(digest), await _digest_html_url(digest))
        if edit:
            edited = await safe_edit_message(message, LONG_DIGEST_TEXT, reply_markup=markup)
            if edited:
                return
        await message.answer(LONG_DIGEST_TEXT, reply_markup=markup)
        return

    keyboard = digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)
    if edit:
        edited = await safe_edit_message(message, digest.digest_text, reply_markup=keyboard, parse_mode="HTML")
        if edited:
            return
    await message.answer(digest.digest_text, reply_markup=keyboard, disable_web_page_preview=True, parse_mode="HTML")


async def _send_digest_parts(message: Message, digest, *, history_page: int | None = None) -> None:
    parts = split_digest_into_parts(digest.digest_text)
    if len(parts) <= 1:
        await _show_digest_or_fallback(message, digest, edit=True)
        return

    last_markup = (
        digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)
        if history_page is None
        else history_digest(digest.id, history_page, digest.is_favorite)
    )

    edited = await safe_edit_message(message, parts[0], parse_mode="HTML")
    start_index = 1 if edited else 0
    if start_index == 0:
        await message.answer(parts[0], disable_web_page_preview=True, parse_mode="HTML")
        start_index = 1

    for index in range(start_index, len(parts)):
        reply_markup = last_markup if index == len(parts) - 1 else None
        await message.answer(parts[index], reply_markup=reply_markup, disable_web_page_preview=True, parse_mode="HTML")


async def _selected_sources_count(user_id: int) -> int:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, user_id, None)
        return len(await queries.selected_sources(session, user.id))


async def _maybe_warn_about_many_sources(callback: CallbackQuery, mode: str, period: str) -> bool:
    sources_count = await _selected_sources_count(callback.from_user.id)
    if sources_count <= MANY_SOURCES_THRESHOLD:
        return False
    await safe_edit_message(
        callback.message,
        "Вы выбрали много источников. Дайджест может получиться объемным.",
        reply_markup=too_many_sources_warning(mode, period),
    )
    return True


async def _run_digest_generation(callback: CallbackQuery, mode: str, period: str) -> None:
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
    await _show_digest_or_fallback(target_message, digest, edit=True)


@router.callback_query(F.data == "digest:start")
async def choose_digest_mode(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(
        callback.message,
        "Как сформировать дайджест?\n\n"
        "📡 По источникам — бот соберет новости из выбранных RSS-лент.\n\n"
        "🎯 По интересам — бот использует только выбранные вами источники и сортирует новости по вашим темам.",
        reply_markup=digest_mode(),
    )


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
                "Сначала укажите интересы. Потом можно выбрать источники и сформировать дайджест по интересам.",
                reply_markup=interests_need_topics(),
            )
            return
        if not selected:
            await safe_edit_message(
                callback.message,
                "У вас пока нет выбранных источников. Сначала добавьте их, чтобы сформировать дайджест по интересам.",
                reply_markup=interests_need_sources(),
            )
            return

    if mode == "selected_sources" and not selected:
        await safe_edit_message(
            callback.message,
            "У вас пока нет выбранных источников. Сначала добавьте их, а потом сформируйте дайджест.",
            reply_markup=interests_need_sources(),
        )
        return

    await safe_edit_message(callback.message, "За какой период подготовить дайджест?", reply_markup=digest_period(mode))


@router.callback_query(F.data.startswith("digest:period:"))
async def generate_digest(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, mode, period = callback.data.split(":")
    if await _maybe_warn_about_many_sources(callback, mode, period):
        return
    await _run_digest_generation(callback, mode, period)


@router.callback_query(F.data.startswith("digest:confirm_large:"))
async def confirm_large_sources_digest(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, mode, period = callback.data.split(":")
    await _run_digest_generation(callback, mode, period)


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
        await callback.message.edit_reply_markup(
            reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)
        )


@router.callback_query(F.data.startswith("fb:"))
async def feedback(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Спасибо за вашу оценку")
    _, digest_id, value = callback.data.split(":")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, int(digest_id), user.id)
        if digest:
            await queries.set_feedback(session, digest, value)
            await callback.message.edit_reply_markup(
                reply_markup=digest_actions(
                    digest.id,
                    digest.refresh_attempts_left,
                    digest.is_favorite,
                    include_feedback=False,
                )
            )
    await callback.message.answer(main_menu_text(), reply_markup=main_menu())


@router.callback_query(F.data.startswith("refresh:empty:"))
async def refresh_empty(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Попытки обновления для этого дайджеста закончились", show_alert=True)


@router.callback_query(F.data.startswith("digest:shorten_empty:"))
async def shorten_empty(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Лимит коротких версий исчерпан", show_alert=True)


@router.callback_query(F.data.startswith("digest:parts:"))
async def send_digest_parts(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    digest_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await safe_edit_message(callback.message, "Дайджест не найден.")
            return
    await _send_digest_parts(callback.message, digest)


@router.callback_query(F.data.startswith("digest:shorten:"))
async def shorten_digest(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    digest_id = int(callback.data.split(":")[2])
    await safe_edit_message(callback.message, "Сжимаю дайджест до короткой версии...")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await safe_edit_message(callback.message, "Дайджест не найден.")
            return
        if _shorten_attempts_left(digest) <= 0:
            await safe_callback_answer(callback, "Лимит коротких версий исчерпан", show_alert=True)
            await safe_edit_message(
                callback.message,
                LONG_DIGEST_TEXT,
                reply_markup=long_digest_options(digest.id, 0, await _digest_html_url(digest)),
            )
            return
        try:
            short_text = await GigaChatDigestClient(user.llm_provider).shorten(digest.digest_text)
        except Exception:
            short_text = ""

        if not short_text or len(short_text) > SAFE_TELEGRAM_LIMIT:
            await safe_edit_message(
                callback.message,
                SHORTEN_FAILED_TEXT,
                reply_markup=long_digest_options(
                    digest.id,
                    _shorten_attempts_left(digest),
                    await _digest_html_url(digest),
                    include_shorten=False,
                ),
            )
            return

        await queries.decrement_shorten(session, digest)
        await session.refresh(digest)
        keyboard = digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)
        edited = await safe_edit_message(callback.message, short_text, reply_markup=keyboard, parse_mode="HTML")
        if not edited:
            await callback.message.answer(short_text, reply_markup=keyboard, disable_web_page_preview=True, parse_mode="HTML")


@router.callback_query(F.data.startswith("refresh:ask:"))
async def ask_refresh(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    digest_id = int(callback.data.split(":")[2])
    await callback.message.answer(
        "Проверить новые новости?\n"
        "Попытка обновления спишется только если найдутся новые материалы и получится собрать новый дайджест.",
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
        new_digest = await refresh_digest(session, user, digest)
        if not new_digest:
            await callback.message.answer("Новых новостей пока нет. Попытка обновления не списана.")
            return
        await queries.decrement_refresh(session, digest)
        await _show_digest_or_fallback(callback.message, new_digest, edit=False)
