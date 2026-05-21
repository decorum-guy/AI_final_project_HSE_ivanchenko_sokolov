from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Получить дайджест сейчас", callback_data="digest:start")
    kb.button(text="🎯 Мои интересы", callback_data="interests:show")
    kb.button(text="📡 Источники", callback_data="sources:show")
    kb.button(text="⭐ Мои подписки", callback_data="subs:show")
    kb.button(text="🕒 Расписание", callback_data="schedule:show")
    kb.button(text="📚 История дайджестов", callback_data="history:0")
    kb.button(text="⚙️ Настройки", callback_data="settings:show")
    kb.button(text="❓ Помощь", callback_data="help")
    kb.adjust(1)
    return kb.as_markup()


def back_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data="menu")
    return kb.as_markup()

