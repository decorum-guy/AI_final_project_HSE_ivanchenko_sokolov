from __future__ import annotations

import logging
from html import escape
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.core.rss import NewsItem


logger = logging.getLogger(__name__)


def _extract_answer(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        return str(response)

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    if message is None and isinstance(first_choice, dict):
        message = first_choice.get("message")

    if isinstance(message, dict):
        return str(message.get("content", "")).strip()

    return str(getattr(message, "content", "")).strip()


async def ask_gigachat(
    prompt: str,
    *,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    model: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    if not settings.gigachat_credentials:
        raise RuntimeError("GIGACHAT_CREDENTIALS is empty")

    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole

    payload_kwargs: dict[str, Any] = {
        "model": model,
        "messages": [Messages(role=MessagesRole.USER, content=prompt)],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        payload_kwargs["response_format"] = response_format

    payload = Chat(**payload_kwargs)

    async with GigaChat(
        credentials=settings.gigachat_credentials,
        verify_ssl_certs=False,
        timeout=60,
    ) as client:
        response = await client.achat(payload)

    answer = _extract_answer(response)
    if not answer:
        raise RuntimeError("GigaChat returned an empty response")
    return answer


class GigaChatDigestClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def summarize(self, items: list[NewsItem], period_title: str) -> str:
        if not self.settings.gigachat_credentials:
            logger.warning("GIGACHAT_CREDENTIALS is empty, using fallback digest")
            return self._fallback_digest(items, period_title)

        prompt = self._build_digest_prompt(items, period_title)
        logger.info("Sending digest prompt to GigaChat: items=%s chars=%s", len(items), len(prompt))
        try:
            return await ask_gigachat(prompt, max_tokens=1800, temperature=0.25)
        except Exception as exc:
            logger.exception("GigaChat digest request failed, using fallback: %s", exc)
            return self._fallback_digest(items, period_title)

    def _build_digest_prompt(self, items: list[NewsItem], period_title: str) -> str:
        lines = [
            "Ты — редактор персонального новостного дайджеста.",
            "",
            f"Период: {period_title}.",
            "",
            "Сформируй дайджест на русском языке в формате Telegram-compatible HTML.",
            "Правила:",
            "1. Не придумывай факты, используй только переданные новости.",
            "2. Используй <b>...</b> для заголовков блоков и названий новостей.",
            "3. Используй <blockquote>...</blockquote> для короткого вводного блока и итога.",
            "4. Все ссылки оформляй только как <a href=\"URL\">Название источника</a>.",
            "5. Не выводи голые URL.",
            "6. Не используй Markdown: никаких **жирных**, [текст](url) и # заголовков.",
            "7. Символы <, >, & в обычном тексте экранируй или не используй вне HTML-тегов.",
            "8. Ответ должен быть готов к отправке в Telegram с parse_mode='HTML'.",
            "9. После вводного блока обязательно добавь короткий слоган дайджеста: одну яркую строку без тега blockquote.",
            "10. Слоган должен идти сразу после краткого описания и перед первой новостью.",
            "",
            "Структура ответа:",
            f"<b>📰 Дайджест {period_title}</b>",
            "<blockquote>Коротко: 2–3 главные темы дайджеста одним абзацем.</blockquote>",
            "<i>Короткий слоган дайджеста в одну строку.</i>",
            "",
            "<b>1. Заголовок новости</b>",
            "Кратко: 1–2 предложения по сути новости.",
            "Почему важно: короткое объяснение значения новости.",
            "Источник: <a href=\"URL\">Название источника</a>",
            "",
            "<b>Итог</b>",
            "<blockquote>Короткий вывод по общей повестке.</blockquote>",
            "",
            "Новости:",
        ]
        for index, item in enumerate(items, start=1):
            published = item.published.strftime("%d.%m.%Y") if isinstance(item.published, datetime) else "дата не указана"
            lines.extend(
                [
                    f"{index}. {item.title}",
                    f"Источник: {item.source}",
                    f"Категория: {item.category}",
                    f"Дата: {published}",
                    f"Описание: {item.summary or 'нет описания'}",
                    f"Ссылка: {item.link}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _fallback_digest(self, items: list[NewsItem], period_title: str) -> str:
        if not items:
            return (
                f"<b>📰 Дайджест {escape(period_title)}</b>\n\n"
                "<blockquote>Подходящих новостей пока не найдено.</blockquote>\n"
                "<i>Сегодня новостная пауза — тоже часть повестки.</i>"
            )
        slogan = self._fallback_slogan(items)
        lines = [
            f"<b>📰 Дайджест {escape(period_title)}</b>",
            "",
            "<blockquote>Коротко: собрал свежие новости из выбранных RSS-источников.</blockquote>",
            f"<i>{escape(slogan)}</i>",
            "",
        ]
        for index, item in enumerate(items[:12], start=1):
            published = item.published.strftime("%d.%m.%Y") if item.published else "дата не указана"
            source = escape(item.source)
            title = escape(item.title)
            summary = escape(item.summary or "Краткое описание в RSS не указано.")
            if item.link:
                source_line = f'Источник: <a href="{escape(item.link, quote=True)}">{source}</a>'
            else:
                source_line = f"Источник: {source}"
            lines.extend(
                [
                    f"<b>{index}. {title}</b>",
                    f"Кратко: {summary}",
                    f"Почему важно: материал относится к выбранной повестке за период, дата: {escape(published)}.",
                    source_line,
                    "",
                ]
            )
        lines.append("")
        lines.append("<b>Итог</b>")
        lines.append("<blockquote>Это резервная версия дайджеста из RSS-заголовков, потому что GigaChat сейчас недоступен.</blockquote>")
        return "\n".join(lines)

    def _fallback_slogan(self, items: list[NewsItem]) -> str:
        categories = []
        for item in items:
            if item.category and item.category not in categories:
                categories.append(item.category)
            if len(categories) >= 2:
                break
        if len(categories) >= 2:
            return f"{categories[0]} и {categories[1]} задают тон сегодняшней повестке."
        if categories:
            return f"{categories[0]} сегодня в центре внимания."
        return "Главные новости коротко: от сигналов рынка до технологических сдвигов."
