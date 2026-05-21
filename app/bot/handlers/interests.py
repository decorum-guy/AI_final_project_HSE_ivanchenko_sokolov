from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main import back_main
from app.db import queries
from app.db.database import async_session


router = Router()


class InterestState(StatesGroup):
    waiting_text = State()


@router.callback_query(F.data == "interests:show")
async def interests_screen(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    current = user.interests_text or "Пока не указаны"
    await state.set_state(InterestState.waiting_text)
    await callback.message.edit_text(
        f"🎯 Мои интересы\n\nТекущие интересы: {current}\n\nОтправьте одним сообщением темы, которые вам интересны.",
        reply_markup=back_main(),
    )
    await callback.answer()


@router.message(InterestState.waiting_text)
async def save_interests_text(message: Message, state: FSMContext) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(session, message.from_user.id, message.from_user.username)
        await queries.save_interests(session, user, message.text or "")
    await state.clear()
    await message.answer("Интересы сохранены.", reply_markup=back_main())

