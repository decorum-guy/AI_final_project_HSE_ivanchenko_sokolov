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
        "1. Настройте интересы или выберите источники.\n"
        "2. Запросите дайджест сейчас или включите расписание.\n"
        "3. Все дайджесты автоматически попадают в историю.\n"
        "4. Избранное, оценки и обновления доступны под каждым свежим дайджестом.",
        reply_markup=back_main(),
    )
