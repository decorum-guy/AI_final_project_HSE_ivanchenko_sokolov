from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def settings_menu(silent: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Часовой пояс", callback_data="settings:timezone", style="primary")
    toggle = "выключить" if silent else "включить"
    kb.button(text=f"🔕 Тихий режим: {toggle}", callback_data="settings:silent", style="warning" if silent else "success")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()

