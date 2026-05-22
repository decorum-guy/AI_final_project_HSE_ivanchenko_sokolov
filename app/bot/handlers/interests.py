from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.interests import (
    interests_after_save,
    interests_edit_choice,
    interests_edit_back,
    interests_menu,
    keywords_delete_menu,
    keywords_menu,
    recommendation_review_menu,
    recommendations_menu,
)
from app.bot.utils import safe_callback_answer, safe_edit_message
from app.core.recommender import keywords_text, normalize_interests, parse_keywords, recommend_sources
from app.db import queries
from app.db.database import async_session


router = Router()


class InterestState(StatesGroup):
    waiting_text = State()
    waiting_keyword_add = State()


def _interests_text(current: str | None, keywords: str | None) -> str:
    current_text = escape(current or "Пока не указаны")
    normalized = escape(keywords or "Пока не нормализованы")
    return (
        "🎯 Мои интересы\n\n"
        "Здесь можно указать темы, которые вам интересны.\n"
        "На основе интересов бот подберет источники, а нормализованные слова помогут точнее ранжировать новости.\n\n"
        "<b>Текущие интересы:</b>\n"
        f"{current_text}\n\n"
        "<b>Нормализованные слова:</b>\n"
        f"{normalized}"
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
    await safe_edit_message(callback.message, _interests_text(user.interests_text, user.interests_keywords), reply_markup=interests_menu(), parse_mode="HTML")


@router.callback_query(F.data == "interests:edit")
async def edit_interests(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    await state.clear()
    await safe_edit_message(
        callback.message,
        "Как изменить интересы?\n\n"
        "✏️ Свободный текст + ИИ — вы пишете обычную фразу, а ИИ нормализует ее в список слов.\n\n"
        "🧩 Слова вручную — вы сами добавляете или удаляете нормализованные слова без обращения к ИИ.",
        reply_markup=interests_edit_choice(),
    )


@router.callback_query(F.data == "interests:edit:text")
async def edit_interests_text(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    await state.set_state(InterestState.waiting_text)
    await safe_edit_message(
        callback.message,
        "Напишите ваши интересы одним сообщением.\n\nНапример:\nИИ, технологии, стартапы, маркетинг, кино, наука",
        reply_markup=interests_edit_back(),
    )


@router.message(InterestState.waiting_text)
async def save_interests_text(message: Message, state: FSMContext) -> None:
    raw_text = message.text or ""
    async with async_session() as session:
        user = await queries.get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )
        keywords = await normalize_interests(raw_text, user.llm_provider)
        await queries.save_interests(session, user, raw_text, keywords)
    await state.clear()
    await message.answer(
        "Интересы сохранены.\n\n"
        f"Вы ввели:\n{raw_text.strip() or 'Пусто'}\n\n"
        "ИИ нормализовал в слова:\n"
        f"{keywords_text(keywords) or 'Не удалось выделить слова'}\n\n"
        "Эти слова можно отредактировать вручную.",
        reply_markup=interests_after_save(),
    )


@router.callback_query(F.data == "interests:keywords")
async def edit_keywords_screen(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    await state.clear()
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    keywords = parse_keywords(user.interests_keywords)
    await safe_edit_message(
        callback.message,
        "🧩 Нормализованные слова\n\n"
        f"{keywords_text(keywords) or 'Пока слов нет.'}\n\n"
        "Пишите слова в начальной форме: например, «игра» вместо «игры», «театр» вместо «театром».",
        reply_markup=keywords_menu(keywords),
    )


@router.callback_query(F.data == "interests:keyword:add")
async def add_keyword_start(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_callback_answer(callback)
    await state.set_state(InterestState.waiting_keyword_add)
    await safe_edit_message(
        callback.message,
        "Напишите одно слово или несколько слов через запятую.\n\n"
        "Пожалуйста, используйте начальную форму слова: «игра», «театр», «маркетинг».",
        reply_markup=interests_edit_back(),
    )


@router.message(InterestState.waiting_keyword_add)
async def add_keyword_save(message: Message, state: FSMContext) -> None:
    new_keywords = parse_keywords(message.text)
    async with async_session() as session:
        user = await queries.get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )
        keywords = parse_keywords(user.interests_keywords)
        existing = set(keywords)
        for word in new_keywords:
            if word not in existing:
                keywords.append(word)
                existing.add(word)
        await queries.save_interests_keywords(session, user, keywords)
    await state.clear()
    await message.answer(
        "Список слов обновлен.\n\n"
        f"Нормализованные слова:\n{keywords_text(keywords) or 'Пока слов нет.'}",
        reply_markup=keywords_menu(keywords),
    )


@router.callback_query(F.data == "interests:keyword:delete_menu")
async def delete_keyword_menu(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    keywords = parse_keywords(user.interests_keywords)
    if not keywords:
        await safe_callback_answer(callback, "Список слов пуст", show_alert=True)
        return
    await safe_edit_message(
        callback.message,
        "Выберите слово, которое нужно удалить:",
        reply_markup=keywords_delete_menu(keywords),
    )


@router.callback_query(F.data.startswith("interests:keyword:delete:"))
async def delete_keyword(callback: CallbackQuery) -> None:
    await safe_callback_answer(callback, "Удалено")
    index = int(callback.data.rsplit(":", 1)[1])
    async with async_session() as session:
        user = await queries.get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        keywords = parse_keywords(user.interests_keywords)
        if 0 <= index < len(keywords):
            keywords.pop(index)
            await queries.save_interests_keywords(session, user, keywords)
    await safe_edit_message(
        callback.message,
        "🧩 Нормализованные слова\n\n"
        f"{keywords_text(keywords) or 'Пока слов нет.'}\n\n"
        "Пишите слова в начальной форме: «игра», «театр», «маркетинг».",
        reply_markup=keywords_menu(keywords),
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
        recommendation_query = user.interests_keywords or user.interests_text
        recommendations = await recommend_sources(recommendation_query, sources, user.llm_provider)
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
