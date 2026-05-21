from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.core.rss import NewsItem
from app.db.models import NewsSource


logger = logging.getLogger(__name__)
POPULAR_CATEGORIES = {"it", "бизнес", "технологии", "наука", "международные"}


@dataclass(frozen=True)
class SourceRecommendation:
    source_id: str
    reason: str


def _words(text: str | None) -> set[str]:
    return {word for word in re.findall(r"[a-zA-Zа-яА-Я0-9]+", (text or "").lower()) if len(word) > 2}


def relevance_score(text: str, interests_text: str | None) -> int:
    interests = _words(interests_text)
    if not interests:
        return 0
    words = _words(text)
    return len(interests & words)


def filter_by_interests(items: list[NewsItem], interests_text: str | None) -> list[NewsItem]:
    if not interests_text:
        return items
    ranked = sorted(
        items,
        key=lambda item: (
            relevance_score(f"{item.title} {item.summary} {item.source} {item.category}", interests_text),
            item.published is not None,
            item.published,
        ),
        reverse=True,
    )
    return ranked


async def recommend_sources(interests_text: str, sources: list[NewsSource]) -> list[SourceRecommendation]:
    if get_settings().gigachat_credentials:
        prompt = _build_recommendation_prompt(interests_text, sources)
        logger.info("GigaChat recommendation prompt prepared, chars=%s", len(prompt))
        # Реальный вызов GigaChat можно подключить здесь. Для MVP fallback остается обязательным,
        # чтобы сценарий работал без внешнего API или при ошибке SDK.
    return fallback_recommend_sources(interests_text, sources)


def fallback_recommend_sources(interests_text: str, sources: list[NewsSource]) -> list[SourceRecommendation]:
    interest_words = _words(interests_text)
    scored: list[tuple[int, NewsSource]] = []
    for source in sources:
        haystack = f"{source.title} {source.category} {source.description}"
        score = len(interest_words & _words(haystack))
        if score:
            scored.append((score, source))

    scored.sort(key=lambda pair: (pair[0], pair[1].title), reverse=True)
    chosen = [source for _, source in scored[:10]]
    if len(chosen) < 5:
        existing = {source.source_id for source in chosen}
        for source in sources:
            if source.source_id in existing:
                continue
            if source.category.lower() in POPULAR_CATEGORIES:
                chosen.append(source)
                existing.add(source.source_id)
            if len(chosen) >= 10:
                break
    if len(chosen) < 5:
        existing = {source.source_id for source in chosen}
        for source in sources:
            if source.source_id not in existing:
                chosen.append(source)
                existing.add(source.source_id)
            if len(chosen) >= 10:
                break

    return [
        SourceRecommendation(
            source_id=source.source_id,
            reason=f"Подходит по категории «{source.category}» и описанию источника.",
        )
        for source in chosen[:10]
    ]


def _build_recommendation_prompt(interests_text: str, sources: list[NewsSource]) -> str:
    sources_list = "\n".join(
        f"- source_id: {source.source_id}; title: {source.title}; category: {source.category}; description: {source.description or ''}"
        for source in sources
    )
    schema = {
        "recommendations": [
            {
                "source_id": "habr_articles",
                "reason": "Подходит, потому что источник пишет про IT, разработку и технологии.",
            }
        ]
    }
    return (
        "Ты — помощник по подбору RSS-источников для персонального новостного дайджеста.\n\n"
        f"Интересы пользователя:\n{interests_text}\n\n"
        f"Список доступных источников:\n{sources_list}\n\n"
        "Выбери от 5 до 10 наиболее подходящих источников.\n\n"
        "Правила:\n"
        "1. Выбирай только source_id из переданного списка.\n"
        "2. Не придумывай новые источники.\n"
        "3. Не меняй source_id.\n"
        "4. Учитывай category, title и description.\n"
        "5. Верни ответ строго в JSON.\n\n"
        f"Формат JSON:\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )
