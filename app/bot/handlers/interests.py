from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.interests import (
    interests_after_save,
    interests_edit_back,
    interests_menu,
    recommendation_review_menu,
    recommendations_menu,
)
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


def _recommendations_text(recommendations: list[dict], source_by_id: dict[str, object]) -> str:
    lines = ["🤖 Рекомендованные источники", "", "Я подобрал источники на основе ваших интересов:"]
    for index, item in enumerate(recommendations, start=1):
        source_id = item["source_id"]
        source = source_by_id.get(source_id)
        title = escape(source.title if source else source_id)
        reason = escape(item["reason"])
        removed_note = " <s>(Удалено пользователем)</s>" if item.get("removed") else ""
        lines.append(f"\n{index}. {title}{removed_note}\nПочему подходит: {reason}")
    return "\n".join(lines)


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
        reply_markup=interests_edit_back(),
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
        await queries.sync_sources(session)
        sources = await queries.list_sources(session)
        recommendations = await recommend_sources(user.interests_text, sources)
        source_by_id = {source.source_id: source for source in sources}

    recommendation_data = [
        {"source_id": item.source_id, "reason": item.reason, "removed": False}
        for item in recommendations
    ]
    await state.update_data(recommendations=recommendation_data)
    text = _recommendations_text(recommendation_data, source_by_id)
    target = loading or callback.message
    edited = await safe_edit_message(target, text, reply_markup=recommendations_menu(), parse_mode="HTML")
    if not edited:
        await callback.message.answer(text, reply_markup=recommendations_menu(), parse_mode="HTML")


@router.callback_query(F.data == "interests:review_recommended")
async def review_recommended_sources(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    data = await state.get_data()
    recommendations = data.get("recommendations") or []
    if not recommendations:
        await safe_callback_answer(callback, "Сначала подберите источники", show_alert=True)
        return
    source_ids = [item["source_id"] for item in recommendations]
    async with async_session() as session:
        sources = await queries.sources_by_ids(session, source_ids)
    source_by_id = {source.source_id: source for source in sources}
    items = [
        (
            item["source_id"],
            source_by_id.get(item["source_id"]).title if source_by_id.get(item["source_id"]) else item["source_id"],
            bool(item.get("removed")),
        )
        for item in recommendations
    ]
    await safe_edit_message(
        callback.message,
        "⚙️ Изменение подборки\n\nНажмите на источник, чтобы убрать или вернуть его.",
        reply_markup=recommendation_review_menu(items),
    )


@router.callback_query(F.data.startswith("interests:toggle_recommended:"))
async def toggle_recommended_source(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    source_id = callback.data.removeprefix("interests:toggle_recommended:")
    data = await state.get_data()
    recommendations = data.get("recommendations") or []
    for item in recommendations:
        if item["source_id"] == source_id:
            item["removed"] = not item.get("removed", False)
            break
    await state.update_data(recommendations=recommendations)
    source_ids = [item["source_id"] for item in recommendations]
    async with async_session() as session:
        sources = await queries.sources_by_ids(session, source_ids)
    source_by_id = {source.source_id: source for source in sources}
    items = [
        (
            item["source_id"],
            source_by_id.get(item["source_id"]).title if source_by_id.get(item["source_id"]) else item["source_id"],
            bool(item.get("removed")),
        )
        for item in recommendations
    ]
    await callback.message.edit_reply_markup(reply_markup=recommendation_review_menu(items))


@router.callback_query(F.data == "interests:save_recommended_review")
@router.callback_query(F.data == "interests:recommendations_back")
async def back_to_recommendations(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback, "Подборка обновлена" if callback.data.endswith("save_recommended_review") else None)
    data = await state.get_data()
    recommendations = data.get("recommendations") or []
    source_ids = [item["source_id"] for item in recommendations]
    async with async_session() as session:
        sources = await queries.sources_by_ids(session, source_ids)
    source_by_id = {source.source_id: source for source in sources}
    await safe_edit_message(
        callback.message,
        _recommendations_text(recommendations, source_by_id),
        reply_markup=recommendations_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "interests:add_recommended")
async def add_recommended_sources(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback, "Источники добавлены")
    data = await state.get_data()
    recommendations = data.get("recommendations") or []
    source_ids = [item["source_id"] for item in recommendations if not item.get("removed")]
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await queries.add_user_sources(session, user.id, list(source_ids))
    await state.clear()
    from app.bot.handlers.sources import show_subscriptions

    await show_subscriptions(callback, prefix="Источники добавлены.\n\n", answer=False)
