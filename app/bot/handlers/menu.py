from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.main import back_main, main_menu


router = Router()


@router.callback_query(F.data == "menu")
async def show_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Главное меню", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "help")
async def help_screen(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "❓ Помощь\n\n"
        "1. Настройте интересы или выберите источники.\n"
        "2. Запросите дайджест сейчас или включите расписание.\n"
        "3. Все дайджесты автоматически попадают в историю.\n"
        "4. Избранное, оценки и обновления доступны под каждым свежим дайджестом.",
        reply_markup=back_main(),
    )
    await callback.answer()

