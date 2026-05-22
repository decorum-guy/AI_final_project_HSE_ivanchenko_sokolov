from math import ceil

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.styles import button
from app.db.models import User


def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="📊 Статистика", callback_data="admin:stats", style="primary")
    button(kb, text="🔍 Проверить RSS", callback_data="admin:rss", style="primary")
    button(kb, text="♻️ Перезагрузить источники", callback_data="admin:reload", style="primary")
    button(kb, text="🧪 Тестовый дайджест", callback_data="admin:test", style="success")
    button(kb, text="📦 Тест длинного дайджеста", callback_data="admin:long", style="success")
    button(kb, text="🧹 Очистить истории", callback_data="admin:history:clear", style="danger")
    button(kb, text="← Назад", callback_data="menu")
    kb.adjust(2, 1, 1, 1, 1, 1)
    return kb.as_markup()


def admin_stats_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="📈 Общая", callback_data="admin:stats:general", style="primary")
    button(kb, text="👥 Пользователи", callback_data="admin:users:0", style="primary")
    button(kb, text="← Назад", callback_data="admin:menu")
    kb.adjust(2, 1)
    return kb.as_markup()


def admin_back(target: str = "admin:menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="← Назад", callback_data=target)
    return kb.as_markup()


def admin_clear_history_confirm() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="✅ Да, очистить", callback_data="admin:history:clear:confirm", style="danger")
    button(kb, text="← Отмена", callback_data="admin:menu")
    kb.adjust(1)
    return kb.as_markup()


def user_title(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or f"User {user.telegram_id}"


def admin_users_list(users: list[User], page: int, total: int, per_page: int = 8) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for user in users:
        button(kb, text=user_title(user), callback_data=f"admin:user:{user.id}:{page}")
    pages = max(1, ceil(total / per_page))
    if pages > 1:
        button(kb, text="←", callback_data=f"admin:users:{max(0, page - 1)}")
        button(kb, text="→", callback_data=f"admin:users:{min(pages - 1, page + 1)}")
    button(kb, text="← Назад", callback_data="admin:stats")
    kb.adjust(*([1] * len(users)), 2 if pages > 1 else 1, 1)
    return kb.as_markup()


def admin_test_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🎯 По интересам", callback_data="admin:test:mode:interests", style="primary")
    button(kb, text="📡 По источникам", callback_data="admin:test:mode:selected_sources", style="primary")
    button(kb, text="← Назад", callback_data="admin:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_test_period(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="Сегодня", callback_data=f"admin:test:period:{mode}:today", style="primary")
    button(kb, text="3 дня", callback_data=f"admin:test:period:{mode}:3days")
    button(kb, text="Неделя", callback_data=f"admin:test:period:{mode}:week")
    button(kb, text="← Назад", callback_data="admin:test")
    kb.adjust(3, 1)
    return kb.as_markup()


def admin_long_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="🎯 По интересам", callback_data="admin:long:mode:interests", style="primary")
    button(kb, text="📡 По источникам", callback_data="admin:long:mode:selected_sources", style="primary")
    button(kb, text="← Назад", callback_data="admin:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_long_period(mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    button(kb, text="Сегодня", callback_data=f"admin:long:period:{mode}:today", style="primary")
    button(kb, text="3 дня", callback_data=f"admin:long:period:{mode}:3days")
    button(kb, text="Неделя", callback_data=f"admin:long:period:{mode}:week")
    button(kb, text="← Назад", callback_data="admin:long")
    kb.adjust(3, 1)
    return kb.as_markup()
