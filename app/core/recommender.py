from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.core.gigachat_client import ask_llm
from app.core.llm_debug import log_llm_event
from app.core.rss import NewsItem
from app.db.models import NewsSource


logger = logging.getLogger(__name__)
POPULAR_CATEGORIES = {"it", "бизнес", "технологии", "наука", "международные"}
MIN_VALID_LLM_RECOMMENDATIONS = 3
MIN_NORMALIZED_KEYWORDS = 3
INTEREST_STOPWORDS = {
    "люблю",
    "интересно",
    "интересует",
    "хочу",
    "нравится",
    "про",
    "для",
    "или",
    "как",
    "что",
    "это",
}
MIN_NORMALIZED_KEYWORDS = 2
MAX_NORMALIZED_KEYWORDS = 8

@dataclass(frozen=True)
class SourceRecommendation:
    source_id: str
    reason: str


def _words(text: str | None) -> set[str]:
    return {word for word in re.findall(r"[a-zA-Zа-яА-Я0-9]+", (text or "").lower()) if len(word) > 2}


def _normalize_keyword_word(word: str) -> str:
    word = word.strip().lower()
    replacements = {
        "рекламу": "реклама",
        "рекламы": "реклама",
        "игры": "игра",
        "игру": "игра",
        "технологии": "технологии",
    }
    if word in replacements:
        return replacements[word]
    if len(word) > 4 and word.endswith("у"):
        return word[:-1] + "а"
    if len(word) > 4 and word.endswith("ю"):
        return word[:-1] + "я"
    return word


def parse_keywords(text: str | None) -> list[str]:
    if not text:
        return []
    words = []
    seen = set()
    for raw_word in re.split(r"[,;\n]+", text):
        word = raw_word.strip().lower()
        word = re.sub(r"\s+", " ", word)
        if " " not in word:
            word = _normalize_keyword_word(word)
        if not word or word in seen:
            continue
        if len(word) <= 2:
            continue
        words.append(word)
        seen.add(word)
    return words[:30]


def keywords_text(keywords: list[str]) -> str:
    return ", ".join(parse_keywords(", ".join(keywords)))


def fallback_normalize_interests(interests_text: str) -> list[str]:
    words = []
    seen = set()
    for word in _words(interests_text):
        if word in INTEREST_STOPWORDS:
            continue
        normalized = _normalize_keyword_word(word)
        if normalized in INTEREST_STOPWORDS or normalized in seen:
            continue
        words.append(normalized)
        seen.add(normalized)
    return sorted(words)[:12]


def _normalization_response_format() -> dict:
    return {
        "type": "json_schema",
        "name": "normalized_interests",
        "schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": MIN_NORMALIZED_KEYWORDS,
                    "maxItems": MAX_NORMALIZED_KEYWORDS,
                },
            },
            "required": ["keywords"],
            "additionalProperties": False,
        },
        "strict": True,
    }


async def normalize_interests(interests_text: str, provider: str | None = None) -> list[str]:
    text = (interests_text or "").strip()
    if not text:
        return []
    prompt = (
        "Ты нормализуешь интересы пользователя для поиска и ранжирования новостей.\n\n"
        f"Интересы пользователя:\n{text}\n\n"
        f"Верни от {MIN_NORMALIZED_KEYWORDS} до {MAX_NORMALIZED_KEYWORDS} ключевых слов или коротких словосочетаний.\n"
        "Правила:\n"
        "1. Пиши на русском языке, если это естественно для термина.\n"
        "2. Слова приводи к начальной форме: «культура», «маркетинг», «технологии».\n"
        "3. Не превращай эмоции в ключевые слова: «люблю», «нравится», «обожаю» нужно удалить.\n"
        "4. Не добавляй служебные слова формата: «новости», «статьи», «материалы», «публикации», если они не являются самостоятельной темой.\n"
        "5. Если пользователь пишет «новости про технологии», ключевая тема — «технологии», а не «новости технологий».\n"
        "6. Не расширяй интересы слишком широко и не добавляй дальние ассоциации.\n"
        "7. Добавляй только темы, которые явно следуют из текста пользователя.\n"
        "8. Если пользователь пишет «люблю культуру, новости про технологии», хороший ответ: "
        "[\"культура\", \"технологии\"].\n"
        "9. Если пользователь пишет «обожаю технологии и культуру», хороший ответ: "
        "[\"технологии\", \"культура\"].\n"
        "10. Ответ строго JSON по схеме."
    )
    try:
        logger.info("Normalizing interests with ChatGPT model gpt-5.4-nano")
        answer = await ask_llm(
            prompt,
            provider="chatgpt",
            model="gpt-5.4-nano",
            max_tokens=500,
            temperature=0.1,
            response_format=_normalization_response_format(),
            task="interest_normalization",
        )
        payload = extract_json_object(answer, task="interest_normalization")
        if isinstance(payload, dict):
            raw_keywords = payload.get("keywords") or []
            keywords = parse_keywords(", ".join(str(item) for item in raw_keywords))
            log_llm_event(
                task="interest_normalization",
                event="parsed",
                provider="chatgpt",
                model="gpt-5.4-nano",
                raw_answer=answer,
                parsed_summary={"keywords_count": len(keywords), "raw_keywords_count": len(raw_keywords)},
            )
            if len(keywords) >= MIN_NORMALIZED_KEYWORDS:
                return keywords[:MAX_NORMALIZED_KEYWORDS]
        log_llm_event(
            task="interest_normalization",
            event="fallback",
            provider="chatgpt",
            model="gpt-5.4-nano",
            raw_answer=answer,
            fallback_reason="too_few_keywords_or_parse_error",
        )
        logger.warning("Interest normalization returned too few keywords, using fallback")
    except Exception as exc:
        log_llm_event(
            task="interest_normalization",
            event="fallback",
            provider="chatgpt",
            model="gpt-5.4-nano",
            error=exc,
            fallback_reason="llm_request_failed",
        )
        logger.exception("Interest normalization failed, using fallback: %s", exc)
    return fallback_normalize_interests(text)


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
        "name": "source_recommendations",
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
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["recommendations"],
            "additionalProperties": False,
        },
        "strict": True,
    }


async def recommend_sources(interests_text: str, sources: list[NewsSource], provider: str | None = None) -> list[SourceRecommendation]:
    active_sources = [source for source in sources if source.is_active]
    valid_source_ids = {source.source_id for source in active_sources}
    settings = get_settings()
    selected_provider = "chatgpt"
    selected_model = "gpt-5.4-nano"
    if settings.openai_api_key and active_sources:
        prompt = _build_recommendation_prompt(interests_text, active_sources)
        logger.info(
            "Sending source recommendation prompt to ChatGPT gpt-5.4-nano: sources=%s chars=%s",
            len(active_sources),
            len(prompt),
        )
        try:
            answer = await ask_llm(
                prompt,
                provider=selected_provider,
                model=selected_model,
                max_tokens=1500,
                temperature=0.1,
                response_format=_recommendation_response_format(),
                task="source_recommendation",
            )
            recommendations, invalid_count = _parse_recommendation_response(answer, valid_source_ids)
            log_llm_event(
                task="source_recommendation",
                event="parsed",
                provider=selected_provider,
                model=selected_model,
                raw_answer=answer,
                parsed_summary={
                    "recommendations_count": len(recommendations),
                    "valid_source_id_count": len(recommendations),
                    "invalid_source_id_count": invalid_count,
                    "available_source_count": len(valid_source_ids),
                },
            )
            if len(recommendations) >= MIN_VALID_LLM_RECOMMENDATIONS:
                if len(recommendations) < 5:
                    existing = {item.source_id for item in recommendations}
                    for item in fallback_recommend_sources(interests_text, active_sources):
                        if item.source_id in existing:
                            continue
                        recommendations.append(item)
                        existing.add(item.source_id)
                        if len(recommendations) >= 5:
                            break
                logger.info("ChatGPT gpt-5.4-nano recommended %s sources", len(recommendations))
                return recommendations
            logger.warning(
                "ChatGPT gpt-5.4-nano recommendation response has too few valid source_id values: %s",
                len(recommendations),
            )
            log_llm_event(
                task="source_recommendation",
                event="fallback",
                provider=selected_provider,
                model=selected_model,
                raw_answer=answer,
                parsed_summary={"valid_source_id_count": len(recommendations), "invalid_source_id_count": invalid_count},
                fallback_reason="too_few_valid_source_ids",
            )
        except Exception as exc:
            log_llm_event(
                task="source_recommendation",
                event="fallback",
                provider=selected_provider,
                model=selected_model,
                error=exc,
                fallback_reason="llm_request_failed",
            )
            logger.exception("ChatGPT gpt-5.4-nano recommendation request failed, using fallback: %s", exc)
    elif active_sources:
        log_llm_event(
            task="source_recommendation",
            event="fallback",
            provider=selected_provider,
            model=selected_model,
            fallback_reason="OPENAI_API_KEY is empty",
            parsed_summary={"available_source_count": len(active_sources)},
        )
        logger.info("ChatGPT gpt-5.4-nano recommendation is not configured, using fallback")
    return fallback_recommend_sources(interests_text, active_sources)


def extract_json_object(raw_text: str, *, task: str = "other") -> dict | None:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        log_llm_event(task=task, event="parse_error", raw_answer=raw_text, error="Cannot find JSON object")
        logger.warning("Cannot find JSON object in LLM response. raw_preview=%r", raw_text[:4000])
        return None

    candidate = text[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        log_llm_event(
            task=task,
            event="parse_error",
            raw_answer=raw_text,
            error=exc,
            extra={"candidate_preview": candidate[:4000]},
        )
        logger.warning(
            "Cannot parse LLM JSON. raw_preview=%r candidate=%r error=%s",
            raw_text[:4000],
            candidate[:4000],
            exc,
        )
        return None

    if not isinstance(payload, dict):
        log_llm_event(
            task=task,
            event="parse_error",
            raw_answer=raw_text,
            error="LLM JSON is not an object",
            extra={"candidate_preview": candidate[:4000]},
        )
        logger.warning(
            "LLM JSON is not an object. raw_preview=%r candidate=%r",
            raw_text[:4000],
            candidate[:4000],
        )
        return None

    return payload


def _parse_recommendation_response(answer: str, valid_source_ids: set[str]) -> tuple[list[SourceRecommendation], int]:
    payload = extract_json_object(answer, task="source_recommendation")
    if payload is None:
        return [], 0

    raw_items = payload.get("recommendations", []) if isinstance(payload, dict) else []
    recommendations: list[SourceRecommendation] = []
    seen: set[str] = set()
    invalid_count = 0
    for item in raw_items:
        if not isinstance(item, dict):
            invalid_count += 1
            continue
        source_id = str(item.get("source_id", "")).strip()
        if source_id not in valid_source_ids or source_id in seen:
            invalid_count += 1
            log_llm_event(
                task="source_recommendation",
                event="invalid_source_id",
                provider="chatgpt",
                model="gpt-5.4-nano",
                raw_answer=answer,
                parsed_summary={"invalid_source_id": source_id},
            )
            logger.warning("Ignoring invalid LLM source_id recommendation: %s", source_id)
            continue
        reason = str(item.get("reason", "")).strip() or "Подходит по интересам пользователя."
        recommendations.append(SourceRecommendation(source_id=source_id, reason=reason))
        seen.add(source_id)
        if len(recommendations) >= 10:
            break

    return recommendations[:10], invalid_count


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
