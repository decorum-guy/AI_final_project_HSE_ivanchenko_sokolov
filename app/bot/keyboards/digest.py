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


def digest_actions(
    digest_id: int,
    attempts_left: int,
    is_favorite: bool,
    include_main_menu: bool = True,
    include_feedback: bool = True,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if attempts_left > 0:
        button(kb, text=f"🔄 Обновить ({attempts_left})", callback_data=f"refresh:ask:{digest_id}", style="primary")
    else:
        button(kb, text="🔄 Обновить (0)", callback_data=f"refresh:empty:{digest_id}")
    button(
        kb,
        text="⭐ Убрать из избранного" if is_favorite else "⭐ В избранное",
        callback_data=f"fav:fresh:{digest_id}",
        style="danger" if is_favorite else "success",
    )
    if include_feedback:
        button(kb, text="👍 Полезно", callback_data=f"fb:{digest_id}:positive", style="success")
        button(kb, text="👎 Не подходит", callback_data=f"fb:{digest_id}:negative", style="danger")
    if include_main_menu:
        button(kb, text="🏠 В главное меню", callback_data="menu:new", style="primary")
        kb.adjust(2, 2 if include_feedback else 1, 1)
    else:
        kb.adjust(2, 2 if include_feedback else 1)
    return kb.as_markup()


def refresh_confirm(digest_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Да, проверить", callback_data=f"refresh:yes:{digest_id}", style="success")
    button(kb, text="← Отмена", callback_data=f"refresh:no:{digest_id}")
    kb.adjust(1)
    return kb.as_markup()


def long_digest_options(
    digest_id: int,
    shorten_attempts_left: int,
    html_url: str = "",
    *,
    include_shorten: bool = True,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if html_url:
        kb.button(text="🌐 Открыть полный дайджест", url=html_url)
    else:
        button(kb, text="🌐 Полный дайджест", callback_data=f"digest:parts:{digest_id}", style="primary")
    button(kb, text="📩 Получить частями", callback_data=f"digest:parts:{digest_id}", style="success")
    if include_shorten and shorten_attempts_left > 0:
        button(
            kb,
            text=f"🔁 Перегенерировать короче ({shorten_attempts_left})",
            callback_data=f"digest:shorten:{digest_id}",
            style="primary",
        )
    elif include_shorten:
        button(kb, text="🔁 Перегенерировать короче (0)", callback_data=f"digest:shorten_empty:{digest_id}")
    button(kb, text="🏠 В главное меню", callback_data="menu:new", style="primary")
    if include_shorten:
        kb.adjust(1, 1, 1, 1)
    else:
        kb.adjust(1, 1, 1)
    return kb.as_markup()


def history_long_digest(digest_id: int, page: int, is_favorite: bool, html_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Открыть полный дайджест", url=html_url)
    button(kb, text="📩 Получить частями", callback_data=f"history:parts:{digest_id}:{page}", style="success")
    button(
        kb,
        text="⭐ Убрать из избранного" if is_favorite else "⭐ В избранное",
        callback_data=f"fav:history:{digest_id}:{page}",
        style="danger" if is_favorite else "success",
    )
    button(kb, text="← Назад", callback_data=f"history:{page}")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def too_many_sources_warning(mode: str, period: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="Продолжить", callback_data=f"digest:confirm_large:{mode}:{period}", style="primary")
    button(kb, text="Уменьшить источники", callback_data="sources:choose:digest")
    kb.adjust(1)
    return kb.as_markup()
