from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button


def interests_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✏️ Изменить интересы", callback_data="interests:edit", style="primary")
    button(kb, text="🤖 Подобрать источники", callback_data="interests:recommend", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def interests_after_save() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🤖 Подобрать источники", callback_data="interests:recommend", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def recommendations_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Добавить все", callback_data="interests:add_recommended", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:subs", style="primary")
    button(kb, text="🔄 Подобрать заново", callback_data="interests:recommend", style="primary")
    button(kb, text="← Назад", callback_data="interests:show")
    kb.adjust(1)
    return kb.as_markup()


def interests_need_sources() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🤖 Подобрать источники", callback_data="interests:recommend", style="success")
    button(kb, text="📡 Выбрать вручную", callback_data="sources:choose:digest", style="primary")
    button(kb, text="← Назад", callback_data="digest:start")
    kb.adjust(1)
    return kb.as_markup()
