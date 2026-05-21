from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="📰 Получить дайджест", callback_data="digest:start", style="primary")
    button(kb, text="🎯 Интересы", callback_data="interests:show")
    button(kb, text="📡 Источники", callback_data="sources:show")
    button(kb, text="⭐ Подписки", callback_data="subs:show")
    button(kb, text="🕒 Расписание", callback_data="schedule:show")
    button(kb, text="📚 История", callback_data="history:0")
    button(kb, text="⚙️ Настройки", callback_data="settings:show")
    button(kb, text="❓ Помощь", callback_data="help")
    kb.adjust(1, 2, 2, 2, 1)
    return kb.as_markup()


def back_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="← Назад", callback_data="menu")
    return kb.as_markup()
