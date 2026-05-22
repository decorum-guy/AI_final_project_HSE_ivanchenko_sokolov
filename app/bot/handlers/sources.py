from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.digest import digest_period
from app.bot.keyboards.main import main_menu, main_menu_text
from app.bot.keyboards.styles import button
from app.bot.utils import safe_callback_answer
from app.db import queries
from app.db.database import async_session


router = Router()
SOURCE_CONTEXTS = {"main", "digest", "subs", "admin_test", "admin_long"}


def _context_back_callback(context: str) -> str:
    if context == "digest":
        return "digest:start"
    if context == "admin_test":
        return "admin:test"
    if context == "admin_long":
        return "admin:long"
    if context == "subs":
        return "subs:show"
    return "menu"


async def _categories_keyboard(context: str, user_id: int | None = None):
    async with async_session() as session:
        categories = await queries.list_categories(session)
        selected = await queries.selected_source_ids(session, user_id) if user_id else set()
        category_stats = []
        for category in categories:
            sources = await queries.sources_by_category(session, category)
            selected_count = sum(1 for source in sources if source.source_id in selected)
            category_stats.append((category, selected_count, len(sources)))
    kb = InlineKeyboardBuilder()
    for index, (category, selected_count, total_count) in enumerate(category_stats):
        label = f"{category} ({selected_count}/{total_count})" if user_id else category
        button(kb, text=label, callback_data=f"sources:cat:{context}:{index}", style="primary")
    if user_id:
        button(kb, text="🧹 Очистить все", callback_data=f"sources:clear_confirm:{context}", style="danger")
    button(kb, text="← Назад", callback_data=_context_back_callback(context))
    category_rows = [2] * (len(categories) // 2)
    if len(categories) % 2:
        category_rows.append(1)
    tail_rows = [1, 1] if user_id else [1]
    kb.adjust(*category_rows, *tail_rows)
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
        )
    button(kb, text="✅ Готово", callback_data=f"sources:done:{context}", style="success")
    button(kb, text="← Назад", callback_data=f"sources:choose:{context}")
    source_rows = [2] * (len(sources) // 2)
    if len(sources) % 2:
        source_rows.append(1)
    kb.adjust(*source_rows, 1, 1)
    return kb.as_markup()


async def _open_categories(callback: CallbackQuery, context: str, answer: bool = True) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await callback.message.edit_text(
        "📡 Выбор источников\n\n"
        "Рядом с категорией показано, сколько источников выбрано: X/Y.\n\n"
        "Оптимально выбрать 3–7 источников. Если выбрать слишком много, дайджест может получиться длинным.\n\n"
        "Сначала выберите категорию:",
        reply_markup=await _categories_keyboard(context, user.id),
    )
    if answer:
        await safe_callback_answer(callback)


@router.callback_query(F.data == "sources:show")
async def sources_screen(callback: CallbackQuery) -> None:
    await _open_categories(callback, "main")


@router.callback_query(F.data.startswith("sources:choose:"))
async def sources_choose_context(callback: CallbackQuery) -> None:
    context = callback.data.split(":")[2]
    if context not in SOURCE_CONTEXTS:
        context = "main"
    await _open_categories(callback, context)


@router.callback_query(F.data.startswith("sources:clear_confirm:"))
async def clear_sources_confirm(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    context = callback.data.split(":")[2]
    if context not in SOURCE_CONTEXTS:
        context = "main"
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Да, очистить", callback_data=f"sources:clear:{context}", style="danger")
    button(kb, text="← Назад", callback_data=f"sources:choose:{context}")
    kb.adjust(1)
    await callback.message.edit_text(
        "Вы уверены, что хотите удалить все выбранные источники?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("sources:clear:"))
async def clear_sources(callback: CallbackQuery) -> None:
    context = callback.data.split(":")[2]
    if context not in SOURCE_CONTEXTS:
        context = "main"
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        deleted = await queries.clear_user_sources(session, user.id)
    if deleted == 0:
        await safe_callback_answer(callback, "Выбранных источников уже нет")
    else:
        await safe_callback_answer(callback, "Источники очищены")
    await _open_categories(callback, context, answer=False)


@router.callback_query(F.data == "subs:clear_confirm")
async def clear_subscriptions_confirm(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Да, очистить", callback_data="subs:clear", style="danger")
    button(kb, text="← Назад", callback_data="subs:show")
    kb.adjust(1)
    await callback.message.edit_text(
        "Вы уверены, что хотите удалить все выбранные источники?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "subs:clear")
async def clear_subscriptions(callback: CallbackQuery) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        deleted = await queries.clear_user_sources(session, user.id)
    await safe_callback_answer(callback, "Подписки очищены" if deleted else "Выбранных источников уже нет")
    prefix = "Подписки очищены.\n\n" if deleted else "Выбранных источников уже нет.\n\n"
    await show_subscriptions(callback, prefix=prefix, answer=False)


@router.callback_query(F.data.startswith("sources:cat:"))
async def category_screen(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, context, index_raw = callback.data.split(":")
    category_index = int(index_raw)
    category = await _category_by_index(category_index)
    if not category:
        await safe_callback_answer(callback, "Категория не найдена", show_alert=True)
        return
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        sources = await queries.sources_by_category(session, category)
    descriptions = []
    for source in sources[:8]:
        if source.description:
            descriptions.append(f"• {source.title}: {source.description[:120]}")
    description_block = "\n\nОписание источников:\n" + "\n".join(descriptions) if descriptions else ""
    await callback.message.edit_text(
        f"📡 {category}\n\n"
        "Выберите источники для дайджеста.\n"
        "Нажмите на источник, чтобы добавить или убрать его.\n\n"
        "✅ — источник выбран, ☐ — источник не выбран.\n\n"
        "Оптимально выбрать 3–7 источников. Если выбрать слишком много, дайджест может получиться длинным."
        f"{description_block}",
        reply_markup=await _sources_keyboard(user.id, context, category_index, category),
    )


@router.callback_query(F.data.startswith("sources:toggle:"))
async def toggle_source(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    _, _, context, index_raw, source_id = callback.data.split(":", 4)
    category_index = int(index_raw)
    category = await _category_by_index(category_index)
    if not category:
        await safe_callback_answer(callback, "Категория не найдена", show_alert=True)
        return
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        selected = await queries.toggle_source(session, user.id, source_id)
    await callback.message.edit_reply_markup(reply_markup=await _sources_keyboard(user.id, context, category_index, category))
    await safe_callback_answer(callback, "Источник добавлен" if selected else "Источник удален")


@router.callback_query(F.data.startswith("sources:done:"))
async def sources_done(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    context = callback.data.split(":")[2]
    if context == "digest":
        await callback.message.edit_text("За какой период подготовить дайджест?", reply_markup=digest_period("selected_sources"))
    elif context == "admin_test":
        from app.bot.keyboards.admin import admin_test_period

        await callback.message.edit_text("За какой период подготовить тестовый дайджест?", reply_markup=admin_test_period("selected_sources"))
    elif context == "admin_long":
        from app.bot.keyboards.admin import admin_long_period

        await callback.message.edit_text("За какой период подготовить тестовый длинный дайджест?", reply_markup=admin_long_period("selected_sources"))
    elif context == "subs":
        await show_subscriptions(callback, prefix="Источники обновлены.\n\n")
    else:
        await callback.message.edit_text(f"Источники обновлены.\n\n{main_menu_text()}", reply_markup=main_menu())


@router.callback_query(F.data == "subs:show")
async def subscriptions(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await show_subscriptions(callback, answer=False)


async def show_subscriptions(callback: CallbackQuery, prefix: str = "", answer: bool = True) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        sources = await queries.selected_sources(session, user.id)
    kb = InlineKeyboardBuilder()
    if not sources:
        text = (
            f"{prefix}⭐ Мои подписки\n\n"
            "У вас пока нет выбранных источников. Добавьте их, чтобы бот мог собрать дайджест."
        )
        button(kb, text="🤖 Подобрать источники по интересам", callback_data="interests:recommend", style="success")
        button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    else:
        lines = "\n\n".join(
            f"{index}. {source.title}" + (f"\n{source.category} — {source.description}" if source.description else f"\n{source.category}")
            for index, source in enumerate(sources, start=1)
        )
        text = (
            f"{prefix}⭐ Мои подписки\n\n"
            f"📡 Ваши подписки:\n\n{lines}\n\n"
            "Теперь можно сформировать дайджест или скорректировать список."
        )
        button(kb, text="📡 Изменить источники", callback_data="sources:choose:subs", style="primary")
        button(kb, text="🧹 Очистить все", callback_data="subs:clear_confirm", style="danger")
        button(kb, text="📰 Получить дайджест", callback_data="digest:start", style="success")
    button(kb, text="🏠 Главное меню", callback_data="menu", style="primary")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    if answer:
        await safe_callback_answer(callback)
