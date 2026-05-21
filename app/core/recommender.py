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
MIN_VALID_GIGACHAT_RECOMMENDATIONS = 3


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


def _recommendation_response_format() -> dict:
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["source_id", "reason"],
                    },
                },
            },
            "required": ["recommendations"],
        },
        "strict": True,
    }


async def recommend_sources(interests_text: str, sources: list[NewsSource]) -> list[SourceRecommendation]:
    active_sources = [source for source in sources if source.is_active]
    valid_source_ids = {source.source_id for source in active_sources}
    if get_settings().gigachat_credentials and active_sources:
        prompt = _build_recommendation_prompt(interests_text, active_sources)
        logger.info("Sending recommendation prompt to GigaChat: sources=%s chars=%s", len(active_sources), len(prompt))
        try:
            answer = await ask_gigachat(
                prompt,
                max_tokens=1500,
                temperature=0.1,
                response_format=_recommendation_response_format(),
            )
            recommendations = _parse_recommendation_response(answer, valid_source_ids)
            if len(recommendations) >= MIN_VALID_GIGACHAT_RECOMMENDATIONS:
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
            logger.warning(
                "GigaChat recommendation response has too few valid source_id values: %s",
                len(recommendations),
            )
        except Exception as exc:
            logger.exception("GigaChat recommendation request failed, using fallback: %s", exc)
    return fallback_recommend_sources(interests_text, active_sources)


def extract_json_object(raw_text: str) -> dict | None:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        logger.warning("Cannot find JSON object in GigaChat response. raw_preview=%r", raw_text[:4000])
        return None

    candidate = text[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Cannot parse GigaChat recommendation JSON. raw_preview=%r candidate=%r error=%s",
            raw_text[:4000],
            candidate[:4000],
            exc,
        )
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "GigaChat recommendation JSON is not an object. raw_preview=%r candidate=%r",
            raw_text[:4000],
            candidate[:4000],
        )
        return None

    return payload


def _parse_recommendation_response(answer: str, valid_source_ids: set[str]) -> list[SourceRecommendation]:
    payload = extract_json_object(answer)
    if payload is None:
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
        "5. Верни только валидный JSON.\n"
        "6. Не используй Markdown.\n"
        "7. Не используй ```json и не оборачивай ответ в code block.\n"
        "8. Не добавляй пояснения до или после JSON.\n"
        "9. Ответ должен начинаться с { и заканчиваться }.\n\n"
        f"Формат JSON:\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )
