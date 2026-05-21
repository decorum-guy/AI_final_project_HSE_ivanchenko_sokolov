from math import ceil

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import User


def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin:stats", style="primary")
    kb.button(text="🔍 Проверить RSS", callback_data="admin:rss", style="primary")
    kb.button(text="♻️ Перезагрузить источники", callback_data="admin:reload", style="warning")
    kb.button(text="🧪 Тестовый дайджест", callback_data="admin:test", style="success")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(2, 1, 1, 1)
    return kb.as_markup()


def admin_stats_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Общая", callback_data="admin:stats:general", style="primary")
    kb.button(text="👥 Пользователи", callback_data="admin:users:0", style="primary")
    kb.button(text="← Назад", callback_data="admin:menu")
    kb.adjust(2, 1)
    return kb.as_markup()


def admin_back(target: str = "admin:menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="← Назад", callback_data=target)
    return kb.as_markup()


def user_title(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or f"User {user.telegram_id}"


def admin_users_list(users: list[User], page: int, total: int, per_page: int = 8) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for user in users:
        kb.button(text=user_title(user), callback_data=f"admin:user:{user.id}:{page}")
    pages = max(1, ceil(total / per_page))
    if pages > 1:
        kb.button(text="←", callback_data=f"admin:users:{max(0, page - 1)}")
        kb.button(text="→", callback_data=f"admin:users:{min(pages - 1, page + 1)}")
    kb.button(text="← Назад", callback_data="admin:stats")
    kb.adjust(*([1] * len(users)), 2 if pages > 1 else 1, 1)
    return kb.as_markup()


def admin_test_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 По интересам", callback_data="admin:test:mode:interests", style="primary")
    kb.button(text="📡 По источникам", callback_data="admin:test:mode:selected_sources", style="primary")
    kb.button(text="← Назад", callback_data="admin:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_test_period(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data=f"admin:test:period:{mode}:today", style="primary")
    kb.button(text="3 дня", callback_data=f"admin:test:period:{mode}:3days")
    kb.button(text="Неделя", callback_data=f"admin:test:period:{mode}:week")
    kb.button(text="← Назад", callback_data="admin:test")
    kb.adjust(3, 1)
    return kb.as_markup()
