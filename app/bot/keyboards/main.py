from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Получить дайджест", callback_data="digest:start", style="primary")
    kb.button(text="🎯 Интересы", callback_data="interests:show")
    kb.button(text="📡 Источники", callback_data="sources:show")
    kb.button(text="⭐ Подписки", callback_data="subs:show")
    kb.button(text="🕒 Расписание", callback_data="schedule:show")
    kb.button(text="📚 История", callback_data="history:0")
    kb.button(text="⚙️ Настройки", callback_data="settings:show")
    kb.button(text="❓ Помощь", callback_data="help")
    kb.adjust(1, 2, 2, 2, 1)
    return kb.as_markup()


def back_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="← Назад", callback_data="menu")
    return kb.as_markup()

