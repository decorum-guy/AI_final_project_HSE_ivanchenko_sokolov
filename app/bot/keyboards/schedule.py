from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button
from app.core.timezones import TIMEZONES


def schedule_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🌅 Каждое утро", callback_data="schedule:type:morning", style="primary")
    button(kb, text="🌙 Каждый вечер", callback_data="schedule:type:evening", style="primary")
    button(kb, text="📅 Раз в неделю", callback_data="schedule:type:weekly")
    button(kb, text="🔕 Отключить", callback_data="schedule:disable", style="danger")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def schedule_times(schedule_type: str) -> InlineKeyboardMarkup:
    times = {
        "morning": ["08:00", "09:00", "10:00"],
        "evening": ["18:00", "19:00", "20:00"],
        "weekly": ["08:00", "09:00", "10:00", "18:00", "19:00", "20:00"],
    }[schedule_type]
    kb = InlineKeyboardBuilder()
    for time in times:
        button(kb, text=time, callback_data=f"schedule:time:{schedule_type}:{time}", style="primary")
    button(kb, text="← Назад", callback_data="schedule:show")
    kb.adjust(3, 3, 1)
    return kb.as_markup()


def timezone_menu(return_to: str = "settings") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for title, zone in TIMEZONES:
        button(kb, text=title, callback_data=f"tz:{return_to}:{zone}")
    button(kb, text="← Назад", callback_data="settings:show" if return_to == "settings" else "schedule:show")
    kb.adjust(2, 2, 2, 2, 2, 2, 1)
    return kb.as_markup()
