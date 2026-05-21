from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.keyboards.main import main_menu
from app.db.database import async_session
from app.db.queries import get_or_create_user


router = Router()


@router.message(CommandStart())
async def start(message: Message) -> None:
    async with async_session() as session:
        await get_or_create_user(session, message.from_user.id, message.from_user.username)
    await message.answer(
        "Привет! Я соберу персональный новостной дайджест по вашим интересам или выбранным RSS-источникам.",
        reply_markup=main_menu(),
    )

