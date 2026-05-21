from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.main import back_main, main_menu
from app.bot.utils import safe_callback_answer, safe_edit_message


router = Router()


@router.callback_query(F.data == "menu")
async def show_menu(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(callback.message, "Главное меню", reply_markup=main_menu())


@router.callback_query(F.data == "help")
async def help_screen(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(
        callback.message,
        "❓ Помощь\n\n"
        "1. Укажите интересы: например, технологии, игры, театр.\n"
        "2. Подберите источники через ИИ или выберите их вручную.\n"
        "3. Запросите дайджест сейчас или включите расписание.\n\n"
        "🎯 По моим интересам\n"
        "Бот берет ваши выбранные источники, но выше ставит новости, которые ближе к вашим интересам.\n\n"
        "📡 По выбранным источникам\n"
        "Бот собирает свежие новости из выбранных подписок без дополнительной персонализации по интересам.\n\n"
        "🤖 ИИ-подбор источников\n"
        "Это отдельный шаг: GigaChat анализирует ваши интересы и список доступных RSS-источников, затем предлагает подходящие подписки. "
        "Это не то же самое, что режим дайджеста по интересам.\n\n"
        "Все дайджесты автоматически попадают в историю. Под свежим дайджестом доступны избранное, оценка и проверка новых новостей.",
        reply_markup=back_main(),
    )
