from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def digest_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 По интересам", callback_data="digest:mode:interests", style="primary")
    kb.button(text="📡 По источникам", callback_data="digest:mode:selected_sources", style="primary")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def digest_period(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data=f"digest:period:{mode}:today", style="primary")
    kb.button(text="3 дня", callback_data=f"digest:period:{mode}:3days")
    kb.button(text="Неделя", callback_data=f"digest:period:{mode}:week")
    kb.button(text="← Назад", callback_data="digest:start")
    kb.adjust(3, 1)
    return kb.as_markup()


def digest_actions(digest_id: int, attempts_left: int, is_favorite: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if attempts_left > 0:
        kb.button(text=f"🔄 Обновить ({attempts_left})", callback_data=f"refresh:ask:{digest_id}", style="primary")
    else:
        kb.button(text="🔄 Обновить (0)", callback_data=f"refresh:empty:{digest_id}")
    fav_text = "⭐ Убрать из избранного" if is_favorite else "⭐ В избранное"
    fav_style = "warning" if is_favorite else "success"
    kb.button(text=fav_text, callback_data=f"fav:fresh:{digest_id}", style=fav_style)
    kb.button(text="👍 Полезно", callback_data=f"fb:{digest_id}:positive", style="success")
    kb.button(text="👎 Не подходит", callback_data=f"fb:{digest_id}:negative", style="danger")
    kb.adjust(2, 2)
    return kb.as_markup()


def refresh_confirm(digest_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, проверить", callback_data=f"refresh:yes:{digest_id}", style="success")
    kb.button(text="← Отмена", callback_data=f"refresh:no:{digest_id}")
    kb.adjust(1)
    return kb.as_markup()

