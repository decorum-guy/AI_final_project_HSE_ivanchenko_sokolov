from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button


def interests_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✏️ Изменить интересы", callback_data="interests:edit", style="primary")
    button(kb, text="🧩 Изменить слова", callback_data="interests:keywords", style="primary")
    button(kb, text="🤖 Подобрать источники", callback_data="interests:recommend", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    button(kb, text="🧹 Очистить интересы", callback_data="interests:clear_confirm", style="danger")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def interests_clear_confirm() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Да, очистить", callback_data="interests:clear", style="danger")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def interests_edit_back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def interests_edit_choice() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✏️ Свободный текст + ИИ", callback_data="interests:edit:text", style="primary")
    button(kb, text="🧩 Слова вручную", callback_data="interests:keywords", style="primary")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def interests_after_save() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🧩 Изменить слова", callback_data="interests:keywords", style="primary")
    button(kb, text="🤖 Подобрать источники", callback_data="interests:recommend", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def recommendations_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Добавить все", callback_data="interests:add_recommended", style="success")
    button(kb, text="⚙️ Изменить подборку", callback_data="interests:review_recommended", style="primary")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    button(kb, text="🔄 Подобрать заново", callback_data="interests:recommend", style="primary")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def keywords_menu(keywords: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="➕ Добавить слова", callback_data="interests:keyword:add", style="success")
    if keywords:
        button(kb, text="➖ Удалить слово", callback_data="interests:keyword:delete_menu", style="danger")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def keywords_delete_menu(keywords: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for index, word in enumerate(keywords):
        button(kb, text=f"➖ {word}", callback_data=f"interests:keyword:delete:{index}", style="danger")
    button(kb, text="← Назад", callback_data="interests:keywords")
    kb.adjust(*([1] * len(keywords)), 1)
    return kb.as_markup()


def recommendation_review_menu(items: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for source_id, title, is_removed in items:
        mark = "☐" if is_removed else "✅"
        button(
            kb,
            text=f"{mark} {title}",
            callback_data=f"interests:toggle_recommended:{source_id}",
            style=None if is_removed else "success",
        )
    button(kb, text="💾 Сохранить", callback_data="interests:save_recommended_review", style="success")
    button(kb, text="← Назад", callback_data="interests:recommendations_back")
    kb.adjust(*([1] * len(items)), 1, 1)
    return kb.as_markup()


def interests_need_sources() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🤖 Подобрать источники по интересам", callback_data="interests:recommend", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:digest", style="primary")
    button(kb, text="🏠 Главное меню", callback_data="menu", style="primary")
    kb.adjust(1)
    return kb.as_markup()


def interests_need_topics() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="Указать интересы", callback_data="interests:edit", style="primary")
    button(kb, text="Выбрать источники вручную", callback_data="sources:choose:digest", style="primary")
    button(kb, text="Главное меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def after_recommended_sources_added() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="📰 Получить дайджест по интересам", callback_data="digest:mode:interests", style="success")
    button(kb, text="📡 Изменить источники", callback_data="sources:choose:subs", style="primary")
    button(kb, text="🏠 Главное меню", callback_data="menu", style="primary")
    kb.adjust(1)
    return kb.as_markup()
