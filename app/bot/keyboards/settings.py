from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button


def settings_menu(silent: bool, provider: str = "gigachat") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🌍 Изменить часовой пояс", callback_data="settings:timezone", style="primary")
    if silent:
        button(kb, text="🔔 Включить звук уведомлений", callback_data="settings:silent", style="success")
    else:
        button(kb, text="🔕 Отключить звук уведомлений", callback_data="settings:silent", style="danger")
    next_provider = "chatgpt" if provider != "chatgpt" else "gigachat"
    current = "ChatGPT" if provider == "chatgpt" else "GigaChat"
    button(kb, text=f"🤖 ИИ-провайдер: {current}", callback_data=f"settings:model:{next_provider}", style="primary")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()
