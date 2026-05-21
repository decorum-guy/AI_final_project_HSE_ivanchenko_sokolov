from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.digest import digest_period
from app.bot.keyboards.main import main_menu
from app.bot.keyboards.styles import button
from app.db import queries
from app.db.database import async_session


router = Router()
SOURCE_CONTEXTS = {"main", "digest", "subs", "admin_test"}


def _context_back_callback(context: str) -> str:
    if context == "digest":
        return "digest:start"
    if context == "admin_test":
        return "admin:test"
    if context == "subs":
        return "subs:show"
    return "menu"


async def _categories_keyboard(context: str):
    async with async_session() as session:
        categories = await queries.list_categories(session)
    kb = InlineKeyboardBuilder()
    for index, category in enumerate(categories):
        button(kb, text=category, callback_data=f"sources:cat:{context}:{index}", style="primary")
    button(kb, text="← Назад", callback_data=_context_back_callback(context))
    kb.adjust(2, 2, 2, 2, 2, 2, 1)
    return kb.as_markup()


async def _category_by_index(index: int) -> str | None:
    async with async_session() as session:
        categories = await queries.list_categories(session)
    if 0 <= index < len(categories):
        return categories[index]
    return None


async def _sources_keyboard(user_id: int, context: str, category_index: int, category: str):
    async with async_session() as session:
        sources = await queries.sources_by_category(session, category)
        selected = await queries.selected_source_ids(session, user_id)
    kb = InlineKeyboardBuilder()
    for source in sources:
        is_selected = source.source_id in selected
        mark = "✅" if is_selected else "☐"
        button(
            kb,
            text=f"{mark} {source.title}",
            callback_data=f"sources:toggle:{context}:{category_index}:{source.source_id}",
            style="success" if is_selected else None,
        )
    button(kb, text="✅ Готово", callback_data=f"sources:done:{context}", style="success")
    button(kb, text="← Назад", callback_data=f"sources:choose:{context}")
    kb.adjust(1)
    return kb.as_markup()


async def _open_categories(callback: CallbackQuery, context: str) -> None:
    await callback.message.edit_text(
        "📡 Выбор источников\n\nСначала выберите категорию:",
        reply_markup=await _categories_keyboard(context),
    )
    await callback.answer()


@router.callback_query(F.data == "sources:show")
async def sources_screen(callback: CallbackQuery) -> None:
    await _open_categories(callback, "main")


@router.callback_query(F.data.startswith("sources:choose:"))
async def sources_choose_context(callback: CallbackQuery) -> None:
    context = callback.data.split(":")[2]
    if context not in SOURCE_CONTEXTS:
        context = "main"
    await _open_categories(callback, context)


@router.callback_query(F.data.startswith("sources:cat:"))
async def category_screen(callback: CallbackQuery) -> None:
    _, _, context, index_raw = callback.data.split(":")
    category_index = int(index_raw)
    category = await _category_by_index(category_index)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await callback.message.edit_text(
        f"📡 {category}\n\nВыберите источники для дайджеста.\nНажмите на источник, чтобы добавить или убрать его.",
        reply_markup=await _sources_keyboard(user.id, context, category_index, category),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sources:toggle:"))
async def toggle_source(callback: CallbackQuery) -> None:
    _, _, context, index_raw, source_id = callback.data.split(":", 4)
    category_index = int(index_raw)
    category = await _category_by_index(category_index)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        selected = await queries.toggle_source(session, user.id, source_id)
    await callback.message.edit_reply_markup(reply_markup=await _sources_keyboard(user.id, context, category_index, category))
    await callback.answer("Источник добавлен" if selected else "Источник удален")


@router.callback_query(F.data.startswith("sources:done:"))
async def sources_done(callback: CallbackQuery) -> None:
    context = callback.data.split(":")[2]
    if context == "digest":
        await callback.message.edit_text("За какой период подготовить дайджест?", reply_markup=digest_period("selected_sources"))
    elif context == "admin_test":
        from app.bot.keyboards.admin import admin_test_period

        await callback.message.edit_text("За какой период подготовить тестовый дайджест?", reply_markup=admin_test_period("selected_sources"))
    elif context == "subs":
        await show_subscriptions(callback, prefix="Источники обновлены.\n\n")
    else:
        await callback.message.edit_text("Источники обновлены.", reply_markup=main_menu())
        await callback.answer()


@router.callback_query(F.data == "subs:show")
async def subscriptions(callback: CallbackQuery) -> None:
    await show_subscriptions(callback)


async def show_subscriptions(callback: CallbackQuery, prefix: str = "") -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        sources = await queries.selected_sources(session, user.id)
    kb = InlineKeyboardBuilder()
    if not sources:
        text = f"{prefix}⭐ Мои подписки\n\nВы пока не выбрали источники."
        button(kb, text="📡 Выбрать источники", callback_data="sources:choose:subs", style="primary")
    else:
        lines = "\n".join(f"✅ {source.title}" for source in sources)
        text = f"{prefix}⭐ Мои подписки\n\nВы выбрали источники:\n\n{lines}"
        button(kb, text="📡 Изменить источники", callback_data="sources:choose:subs", style="primary")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()
