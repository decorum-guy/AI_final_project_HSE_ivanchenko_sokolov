from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.core.gigachat_client import ask_gigachat
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
    active_sources = [source for source in sources if source.is_active]
    valid_source_ids = {source.source_id for source in active_sources}
    if get_settings().gigachat_credentials and active_sources:
        prompt = _build_recommendation_prompt(interests_text, active_sources)
        logger.info("Sending recommendation prompt to GigaChat: sources=%s chars=%s", len(active_sources), len(prompt))
        try:
            answer = await ask_gigachat(prompt, max_tokens=900, temperature=0.1)
            recommendations = _parse_recommendation_response(answer, valid_source_ids)
            if recommendations:
                if len(recommendations) < 5:
                    existing = {item.source_id for item in recommendations}
                    for item in fallback_recommend_sources(interests_text, active_sources):
                        if item.source_id in existing:
                            continue
                        recommendations.append(item)
                        existing.add(item.source_id)
                        if len(recommendations) >= 5:
                            break
                logger.info("GigaChat recommended %s sources", len(recommendations))
                return recommendations
            logger.warning("GigaChat recommendation response did not contain valid source_id values")
        except Exception as exc:
            logger.exception("GigaChat recommendation request failed, using fallback: %s", exc)
    return fallback_recommend_sources(interests_text, active_sources)


def _parse_recommendation_response(answer: str, valid_source_ids: set[str]) -> list[SourceRecommendation]:
    text = answer.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            logger.warning("Cannot parse GigaChat recommendation JSON: %s", answer[:500])
            return []
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("Cannot parse extracted GigaChat recommendation JSON: %s", answer[:500])
            return []

    raw_items = payload.get("recommendations", []) if isinstance(payload, dict) else []
    recommendations: list[SourceRecommendation] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id", "")).strip()
        if source_id not in valid_source_ids or source_id in seen:
            logger.warning("Ignoring invalid GigaChat source_id recommendation: %s", source_id)
            continue
        reason = str(item.get("reason", "")).strip() or "Подходит по интересам пользователя."
        recommendations.append(SourceRecommendation(source_id=source_id, reason=reason))
        seen.add(source_id)
        if len(recommendations) >= 10:
            break

    return recommendations[:10]


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
