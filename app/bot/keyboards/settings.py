from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def settings_menu(silent: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Изменить часовой пояс", callback_data="settings:timezone")
    toggle = "выключить" if silent else "включить"
    kb.button(text=f"🔕 Уведомления без звука: {toggle}", callback_data="settings:silent")
    kb.button(text="Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()

