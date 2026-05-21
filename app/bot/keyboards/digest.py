from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def digest_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 По моим интересам", callback_data="digest:mode:interests")
    kb.button(text="📡 По выбранным источникам", callback_data="digest:mode:selected_sources")
    kb.button(text="Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def digest_period(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="За сегодня", callback_data=f"digest:period:{mode}:today")
    kb.button(text="За последние 3 дня", callback_data=f"digest:period:{mode}:3days")
    kb.button(text="За неделю", callback_data=f"digest:period:{mode}:week")
    kb.button(text="Назад", callback_data="digest:start")
    kb.adjust(1)
    return kb.as_markup()


def digest_actions(digest_id: int, attempts_left: int, is_favorite: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if attempts_left > 0:
        kb.button(text=f"🔄 Проверить новые новости (доступно: {attempts_left} исп.)", callback_data=f"refresh:ask:{digest_id}")
    else:
        kb.button(text="🔄 Проверить новые новости (доступно: 0 исп.)", callback_data=f"refresh:empty:{digest_id}")
    fav_text = "⭐ Удалить из избранного" if is_favorite else "⭐ Добавить в избранное"
    kb.button(text=fav_text, callback_data=f"fav:fresh:{digest_id}")
    kb.button(text="👍 Полезно", callback_data=f"fb:{digest_id}:positive")
    kb.button(text="👎 Не подходит", callback_data=f"fb:{digest_id}:negative")
    kb.adjust(1, 1, 2)
    return kb.as_markup()


def refresh_confirm(digest_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, проверить", callback_data=f"refresh:yes:{digest_id}")
    kb.button(text="Нет, отменить", callback_data=f"refresh:no:{digest_id}")
    kb.adjust(1)
    return kb.as_markup()

