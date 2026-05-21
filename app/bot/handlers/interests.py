from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.interests import interests_after_save, interests_menu, recommendations_menu
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.recommender import recommend_sources
from app.db import queries
from app.db.database import async_session


router = Router()


class InterestState(StatesGroup):
    waiting_text = State()


def _interests_text(current: str | None) -> str:
    return (
        "🎯 Мои интересы\n\n"
        "Здесь можно указать темы, которые вам интересны.\n"
        "На основе интересов бот подберет подходящие RSS-источники.\n\n"
        "Текущие интересы:\n"
        f"{current or 'Пока не указаны'}"
    )


@router.callback_query(F.data == "interests:show")
async def interests_screen(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    await state.clear()
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await safe_edit_message(callback.message, _interests_text(user.interests_text), reply_markup=interests_menu())


@router.callback_query(F.data == "interests:edit")
async def edit_interests(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    await state.set_state(InterestState.waiting_text)
    await safe_edit_message(
        callback.message,
        "Напишите ваши интересы одним сообщением.\n\nНапример:\nИИ, технологии, стартапы, маркетинг, кино, наука",
    )


@router.message(InterestState.waiting_text)
async def save_interests_text(message: Message, state: FSMContext) -> None:
    async with async_session() as session:
        user = await queries.get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )
        await queries.save_interests(session, user, message.text or "")
    await state.clear()
    await message.answer(
        "Интересы сохранены.\n\nТеперь я могу подобрать источники под ваши темы.",
        reply_markup=interests_after_save(),
    )


@router.callback_query(F.data == "interests:recommend")
async def recommend_interests_sources(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    loading = await safe_edit_message(callback.message, "🤖 Подбираю источники по вашим интересам...")
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        if not user.interests_text:
            await safe_edit_message(
                callback.message,
                "Сначала укажите интересы, чтобы я мог подобрать источники.",
                reply_markup=interests_after_save(),
            )
            return
        sources = await queries.list_sources(session)
        recommendations = await recommend_sources(user.interests_text, sources)
        source_by_id = {source.source_id: source for source in sources}

    await state.update_data(recommended_source_ids=[item.source_id for item in recommendations])
    lines = ["🤖 Рекомендованные источники", "", "Я подобрал источники на основе ваших интересов:"]
    for index, item in enumerate(recommendations, start=1):
        source = source_by_id.get(item.source_id)
        title = source.title if source else item.source_id
        lines.append(f"\n{index}. {title}\nПочему подходит: {item.reason}")
    target = loading or callback.message
    edited = await safe_edit_message(target, "\n".join(lines), reply_markup=recommendations_menu())
    if not edited:
        await callback.message.answer("\n".join(lines), reply_markup=recommendations_menu())


@router.callback_query(F.data == "interests:add_recommended")
async def add_recommended_sources(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback, "Источники добавлены")
    data = await state.get_data()
    source_ids = data.get("recommended_source_ids") or []
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.add_user_sources(session, user.id, list(source_ids))
    await state.clear()
    from app.bot.handlers.sources import show_subscriptions

    await show_subscriptions(callback, prefix="Источники добавлены.\n\n", answer=False)
