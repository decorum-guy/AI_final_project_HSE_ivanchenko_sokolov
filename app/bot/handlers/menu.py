from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.main import back_main, main_menu, main_menu_text
from app.bot.utils import safe_callback_answer, safe_edit_message


router = Router()


@router.callback_query(F.data == "menu")
async def show_menu(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(callback.message, main_menu_text(), reply_markup=main_menu())


@router.callback_query(F.data == "menu:new")
async def send_menu(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await callback.message.answer(main_menu_text(), reply_markup=main_menu())


@router.callback_query(F.data == "help")
async def help_screen(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    await safe_edit_message(
        callback.message,
        "<b>❓ Помощь</b>\n\n"
        "<b>Быстрый старт</b>\n"
        "1. Укажите интересы свободным текстом.\n"
        "2. Проверьте нормализованные слова: например, <i>реклама, пиар, маркетинг</i>.\n"
        "3. Подберите источники через ИИ или выберите их вручную.\n"
        "4. Запросите дайджест сейчас или включите расписание.\n\n"
        "<b>🎯 По моим интересам</b>\n"
        "Бот берет ваши выбранные источники и выше ставит новости, которые ближе к нормализованным словам интересов.\n\n"
        "<b>📡 По выбранным источникам</b>\n"
        "Бот собирает свежие новости из выбранных подписок без персональной сортировки по интересам.\n\n"
        "<b>🤖 ИИ-подбор источников</b>\n"
        "Это отдельный шаг: ИИ анализирует ваши интересы и список RSS-источников, затем предлагает подписки. "
        "Он не заменяет режим дайджеста по интересам.\n\n"
        "<b>История и действия</b>\n"
        "Дайджесты сохраняются автоматически. Под свежим дайджестом доступны избранное, оценка и проверка новых новостей.\n\n"
        "<b>⚠️ Важно</b>\n"
        "ИИ может ошибаться в фактах, акцентах и оформлении. В боте есть проверки, fallback и постобработка, но идеальный результат не гарантируется.",
        reply_markup=back_main(),
        parse_mode="HTML",
    )
