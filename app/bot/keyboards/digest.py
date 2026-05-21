from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button


def digest_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🎯 По интересам", callback_data="digest:mode:interests", style="primary")
    button(kb, text="📡 По источникам", callback_data="digest:mode:selected_sources", style="primary")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def digest_period(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="Сегодня", callback_data=f"digest:period:{mode}:today", style="primary")
    button(kb, text="3 дня", callback_data=f"digest:period:{mode}:3days")
    button(kb, text="Неделя", callback_data=f"digest:period:{mode}:week")
    button(kb, text="← Назад", callback_data="digest:start")
    kb.adjust(3, 1)
    return kb.as_markup()


def digest_actions(digest_id: int, attempts_left: int, is_favorite: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if attempts_left > 0:
        button(kb, text=f"🔄 Обновить ({attempts_left})", callback_data=f"refresh:ask:{digest_id}", style="primary")
    else:
        button(kb, text="🔄 Обновить (0)", callback_data=f"refresh:empty:{digest_id}")
    fav_text = "⭐ Убрать из избранного" if is_favorite else "⭐ В избранное"
    fav_style = "danger" if is_favorite else "success"
    button(kb, text=fav_text, callback_data=f"fav:fresh:{digest_id}", style=fav_style)
    button(kb, text="👍 Полезно", callback_data=f"fb:{digest_id}:positive", style="success")
    button(kb, text="👎 Не подходит", callback_data=f"fb:{digest_id}:negative", style="danger")
    kb.adjust(2, 2)
    return kb.as_markup()


def refresh_confirm(digest_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Да, проверить", callback_data=f"refresh:yes:{digest_id}", style="success")
    button(kb, text="← Отмена", callback_data=f"refresh:no:{digest_id}")
    kb.adjust(1)
    return kb.as_markup()


def long_digest_options(digest_id: int, shorten_attempts_left: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if shorten_attempts_left > 0:
        button(
            kb,
            text=f"🔁 Перегенерировать короче ({shorten_attempts_left})",
            callback_data=f"digest:shorten:{digest_id}",
            style="primary",
        )
    else:
        button(kb, text="🔁 Перегенерировать короче (0)", callback_data=f"digest:shorten_empty:{digest_id}")
    button(kb, text="📄 Получить DOCX", callback_data=f"digest:file:docx:{digest_id}", style="success")
    button(kb, text="📕 Получить PDF", callback_data=f"digest:file:pdf:{digest_id}", style="success")
    kb.adjust(1, 2)
    return kb.as_markup()
