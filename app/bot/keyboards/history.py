from math import ceil

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import DigestHistory


def history_list(items: list[DigestHistory], page: int, total: int, per_page: int = 5) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for digest in items:
        star = " ⭐" if digest.is_favorite else ""
        kb.button(text=f"{digest.created_at:%d-%m-%Y}{star}", callback_data=f"history:view:{digest.id}:{page}")
    pages = max(1, ceil(total / per_page))
    if pages > 1:
        prev_page = max(0, page - 1)
        next_page = min(pages - 1, page + 1)
        kb.button(text="⬅️", callback_data=f"history:{prev_page}")
        kb.button(text="➡️", callback_data=f"history:{next_page}")
    kb.button(text="Назад", callback_data="menu")
    kb.adjust(*([1] * len(items)), 2 if pages > 1 else 1, 1)
    return kb.as_markup()


def history_digest(digest_id: int, page: int, is_favorite: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data=f"history:{page}")
    kb.button(text="⭐ Удалить из избранного" if is_favorite else "⭐ Добавить в избранное", callback_data=f"fav:history:{digest_id}:{page}")
    kb.adjust(1)
    return kb.as_markup()

