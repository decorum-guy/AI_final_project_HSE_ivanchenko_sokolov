from __future__ import annotations

import asyncio
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

import feedparser
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.admin import (
    admin_back,
    admin_menu,
    admin_stats_menu,
    admin_test_mode,
    admin_test_period,
    admin_users_list,
    user_title,
)
from app.bot.keyboards.digest import digest_actions
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.config import get_settings
from app.core.digest import build_digest
from app.db import queries
from app.db.database import async_session
from app.db.models import NewsSource


logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    admin_id = get_settings().admin_id
    return admin_id is not None and user_id == admin_id


async def _ensure_admin(event: Message | CallbackQuery) -> bool:
    admin_id = get_settings().admin_id
    if admin_id is None:
        text = "Админ-панель не настроена: ADMIN_ID не задан в .env."
    else:
        text = "У вас нет доступа к админ-панели."

    user_id = event.from_user.id
    if is_admin(user_id):
        return True

    if isinstance(event, Message):
        await event.answer(text)
    else:
        await event.answer(text, show_alert=True)
    return False


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if not await _ensure_admin(message):
        return
    await message.answer("Админ-панель", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:menu")
async def admin_menu_callback(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await callback.message.edit_text("Админ-панель", reply_markup=admin_menu())
    await safe_callback_answer(callback)


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await callback.message.edit_text("📊 Статистика\n\nВыберите раздел:", reply_markup=admin_stats_menu())
    await safe_callback_answer(callback)


@router.callback_query(F.data == "admin:stats:general")
async def admin_general_stats(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    async with async_session() as session:
        stats = await queries.admin_general_stats(session)
    text = (
        "📈 Общая статистика\n\n"
        f"Пользователей: {stats['users_count']}\n"
        f"Дайджестов создано: {stats['digests_count']}\n"
        f"Избранных дайджестов: {stats['favorite_count']}\n"
        f"Оценок 👍: {stats['positive_count']}\n"
        f"Оценок 👎: {stats['negative_count']}\n"
        f"Пользователей с выбранными источниками: {stats['users_with_sources']}\n"
        f"Всего пользовательских подписок на источники: {stats['subscriptions_count']}"
    )
    await callback.message.edit_text(text, reply_markup=admin_back("admin:stats"))
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("admin:users:"))
async def admin_users(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    page = int(callback.data.split(":")[2])
    async with async_session() as session:
        users, total = await queries.users_page(session, page)
    text = "👥 Пользователи\n\nВыберите пользователя, чтобы посмотреть подробности."
    if total == 0:
        text += "\n\nПользователей пока нет."
    await callback.message.edit_text(text, reply_markup=admin_users_list(users, page, total))
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_user_card(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    _, _, user_id_raw, page_raw = callback.data.split(":")
    page = int(page_raw)
    async with async_session() as session:
        user = await queries.get_user_by_id(session, int(user_id_raw))
        if not user:
            await safe_callback_answer(callback, "Пользователь не найден", show_alert=True)
            return
        stats = await queries.admin_user_stats(session, user.id)

    username = f"@{user.username}" if user.username else "нет"
    first_name = user.first_name or "нет"
    last_name = user.last_name or "нет"
    activity = user.last_activity_at.strftime("%d-%m-%Y %H:%M") if user.last_activity_at else "нет данных"
    text = (
        "👤 Пользователь\n\n"
        f"Telegram ID: {user.telegram_id}\n"
        f"Username: {username}\n"
        f"Имя: {first_name}\n"
        f"Фамилия: {last_name}\n\n"
        f"Дайджестов создано: {stats['digests_count']}\n"
        f"Избранных дайджестов: {stats['favorite_count']}\n"
        f"Выбранных источников: {stats['sources_count']}\n\n"
        "Оценки:\n"
        f"👍 Полезно: {stats['positive_count']}\n"
        f"👎 Не подходит: {stats['negative_count']}\n\n"
        f"Последняя активность: {activity}"
    )
    await callback.message.edit_text(text, reply_markup=admin_back(f"admin:users:{page}"))
    await safe_callback_answer(callback)


@dataclass(frozen=True)
class RssCheckResult:
    title: str
    ok: bool
    error: str | None = None


def _check_one_source(source: NewsSource, timeout: int = 8) -> RssCheckResult:
    try:
        if not source.rss_url.startswith(("http://", "https://")):
            return RssCheckResult(source.title, False, "invalid url")
        request = urllib.request.Request(source.rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(1024 * 1024)
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", False):
            logger.warning("RSS check parse warning for %s: %s", source.source_id, getattr(feed, "bozo_exception", "unknown"))
        if not feed.entries:
            return RssCheckResult(source.title, False, "empty feed")
        return RssCheckResult(source.title, True)
    except TimeoutError:
        return RssCheckResult(source.title, False, "timeout")
    except urllib.error.URLError as exc:
        return RssCheckResult(source.title, False, str(exc.reason)[:80])
    except Exception as exc:
        logger.warning("RSS check failed for %s", source.source_id, exc_info=True)
        return RssCheckResult(source.title, False, str(exc)[:80])


@router.callback_query(F.data == "admin:rss")
async def admin_check_rss(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await safe_callback_answer(callback)
    await callback.message.edit_text("Проверяю активные RSS-источники. Это может занять немного времени...")
    async with async_session() as session:
        await queries.sync_sources(session)
        sources = await queries.list_sources(session)
    results = await asyncio.gather(*(asyncio.to_thread(_check_one_source, source) for source in sources))
    ok_count = sum(1 for result in results if result.ok)
    bad = [result for result in results if not result.ok]
    lines = [
        "🔍 Проверка RSS-источников завершена",
        "",
        f"Работают: {ok_count}",
        f"С ошибкой: {len(bad)}",
    ]
    if bad:
        lines.extend(["", "Проблемные источники:"])
        lines.extend(f"- {result.title}: {result.error}" for result in bad[:10])
        if len(bad) > 10:
            lines.append("Показаны первые 10 ошибок.")
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_back("admin:menu"))
    await safe_callback_answer(callback)


@router.callback_query(F.data == "admin:reload")
async def admin_reload_sources(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await safe_callback_answer(callback)
    async with async_session() as session:
        await queries.sync_sources(session)
        active_sources = await queries.list_sources(session)
        categories = await queries.list_categories(session)
    text = (
        "♻️ Источники перезагружены\n\n"
        f"Активных источников: {len(active_sources)}\n"
        f"Категорий: {len(categories)}"
    )
    await callback.message.edit_text(text, reply_markup=admin_back("admin:menu"))
    await safe_callback_answer(callback)


@router.callback_query(F.data == "admin:test")
async def admin_test_digest(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await safe_callback_answer(callback)
    await safe_edit_message(
        callback.message,
        "🧪 Тестовый дайджест\n\nКак сформировать тестовый дайджест?",
        reply_markup=admin_test_mode(),
    )


@router.callback_query(F.data.startswith("admin:test:mode:"))
async def admin_test_mode_selected(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await safe_callback_answer(callback)
    mode = callback.data.split(":")[3]
    if mode == "selected_sources":
        async with async_session() as session:
            user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
            selected = await queries.selected_sources(session, user.id)
        if not selected:
            from app.bot.handlers.sources import _categories_keyboard

            await safe_edit_message(
                callback.message,
                "У вас пока нет выбранных источников. Сначала выберите источники для тестового дайджеста.",
                reply_markup=await _categories_keyboard("admin_test"),
            )
            return
    await safe_edit_message(callback.message, "За какой период подготовить тестовый дайджест?", reply_markup=admin_test_period(mode))


@router.callback_query(F.data.startswith("admin:test:period:"))
async def admin_test_period_selected(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    await safe_callback_answer(callback)
    _, _, _, mode, period = callback.data.split(":")
    loading = await safe_edit_message(callback.message, "⏳ Собираю тестовый дайджест...\n\nПодготавливаю источники и свежие новости.")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        digest = await build_digest(session, user, mode, period)
        text = "🧪 Тестовый дайджест\n\n" + digest.digest_text
        keyboard = digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite)
    edited = await safe_edit_message(loading or callback.message, text, reply_markup=keyboard)
    if not edited:
        await callback.message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)
