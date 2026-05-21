import time

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.keyboards.digest import digest_actions, digest_mode, digest_period, long_digest_options, refresh_confirm
from app.bot.keyboards.interests import interests_menu, interests_need_sources
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.documents import build_digest_docx, build_digest_pdf
from app.core.digest import build_digest, refresh_digest
from app.core.gigachat_client import GigaChatDigestClient
from app.db import queries
from app.db.database import async_session


router = Router()
SAFE_TELEGRAM_LIMIT = 3800
LONG_DIGEST_TEXT = (
    "Дайджест получился слишком объемным для одного сообщения Telegram.\n\n"
    "Можно перегенерировать короткую версию или получить полный файл."
)


def _shorten_attempts_left(digest) -> int:
    return digest.shorten_attempts_left if digest.shorten_attempts_left is not None else 2


async def _show_digest_or_fallback(message: Message, digest, *, edit: bool = True) -> None:
    if len(digest.digest_text) > SAFE_TELEGRAM_LIMIT:
        markup = long_digest_options(digest.id, _shorten_attempts_left(digest))
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


@router.callback_query(F.data == "digest:start")
async def choose_digest_mode(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(
        callback.message,
        "Как сформировать дайджест?\n\n"
        "🎯 По моим интересам — бот берет ваши выбранные источники, но выше ставит новости, которые ближе к вашим темам.\n\n"
        "📡 По выбранным источникам — бот собирает свежие новости из ваших подписок без дополнительной сортировки по интересам.\n\n"
        "Важно: ИИ-подбор источников и дайджест по интересам — разные вещи. Подбор источников помогает выбрать подписки, а режим по интересам персонально ранжирует новости внутри уже выбранных источников.",
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
    await _show_digest_or_fallback(target_message, digest, edit=True)


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


@router.callback_query(F.data.startswith("digest:shorten_empty:"))
async def shorten_empty(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Лимит укорачивающих генераций исчерпан", show_alert=True)


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
            await safe_callback_answer(callback, "Лимит укорачивающих генераций исчерпан", show_alert=True)
            await safe_edit_message(callback.message, LONG_DIGEST_TEXT, reply_markup=long_digest_options(digest.id, 0))
            return
        await queries.decrement_shorten(session, digest)
        await session.refresh(digest)
        try:
            short_text = await GigaChatDigestClient().shorten(digest.digest_text)
        except Exception:
            short_text = ""

        if not short_text or len(short_text) > SAFE_TELEGRAM_LIMIT:
            await safe_edit_message(
                callback.message,
                LONG_DIGEST_TEXT,
                reply_markup=long_digest_options(digest.id, _shorten_attempts_left(digest)),
            )
            return

        keyboard = digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)
        edited = await safe_edit_message(callback.message, short_text, reply_markup=keyboard, parse_mode="HTML")
        if not edited:
            await callback.message.answer(short_text, reply_markup=keyboard, disable_web_page_preview=True, parse_mode="HTML")


@router.callback_query(F.data.startswith("digest:file:"))
async def send_digest_file(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, file_type, digest_id_text = callback.data.split(":")
    digest_id = int(digest_id_text)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await queries.get_digest(session, digest_id, user.id)
        if not digest:
            await safe_callback_answer(callback, "Дайджест не найден", show_alert=True)
            return

    if file_type == "docx":
        try:
            content = build_digest_docx(digest)
        except Exception:
            await callback.message.answer("Не удалось сформировать DOCX-файл. Попробуйте PDF или короткую версию.")
            return
        await callback.message.answer_document(
            BufferedInputFile(content, filename=f"infopulse_digest_{digest.id}.docx"),
            caption="Полная версия дайджеста в DOCX.",
        )
        return

    if file_type == "pdf":
        try:
            content = build_digest_pdf(digest)
        except Exception:
            await callback.message.answer("Не удалось сформировать PDF-файл. Попробуйте DOCX или короткую версию.")
            return
        await callback.message.answer_document(
            BufferedInputFile(content, filename=f"infopulse_digest_{digest.id}.pdf"),
            caption="Полная версия дайджеста в PDF.",
        )
        return

    await safe_callback_answer(callback, "Неизвестный формат файла", show_alert=True)


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
            await _show_digest_or_fallback(callback.message, new_digest, edit=False)
