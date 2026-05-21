from __future__ import annotations

import logging
import re
from datetime import datetime
from html import escape
from typing import Any

from app.config import get_settings
from app.core.rss import NewsItem


logger = logging.getLogger(__name__)

ALLOWED_TAG_RE = re.compile(r"</?(?:b|i|blockquote)>|<a\s+href=\"[^\"]+\">|</a>", re.IGNORECASE)
MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)\)")


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


def sanitize_telegram_html(text: str) -> str:
    """Keep only Telegram-safe tags used by the digest and escape everything else."""
    result: list[str] = []
    position = 0

    for match in ALLOWED_TAG_RE.finditer(text):
        result.append(escape(text[position : match.start()]))
        tag = match.group(0)
        lower_tag = tag.lower()

        if lower_tag.startswith("<a "):
            href_match = re.search(r'href="([^"]+)"', tag, flags=re.IGNORECASE)
            href = href_match.group(1) if href_match else ""
            if href.startswith(("http://", "https://")):
                result.append(f'<a href="{escape(href, quote=True)}">')
            else:
                result.append(escape(tag))
        else:
            result.append(lower_tag)
        position = match.end()

    result.append(escape(text[position:]))
    return "".join(result)


def postprocess_digest_html(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:html|HTML|json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("```html", "").replace("```HTML", "").replace("```json", "").replace("```JSON", "").replace("```", "")
    text = MARKDOWN_LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = MARKDOWN_BOLD_RE.sub(r"<b>\1</b>", text)
    text = sanitize_telegram_html(text)

    if "**" in text:
        logger.warning("Digest post-processing left markdown bold markers in text")
    if _has_early_summary(text):
        logger.warning("Digest structure warning: итог appears before новости")
    _log_digest_quality(text)
    return text


def _has_early_summary(text: str) -> bool:
    news_index = text.lower().find("<b>новости</b>")
    summary_index = text.lower().find("<b>итог</b>")
    return summary_index != -1 and (news_index == -1 or summary_index < news_index)


def _log_digest_quality(text: str) -> None:
    lowered = text.lower()
    if "```" in text or "##" in text or re.search(r"\[[^\]]+]\(https?://", text):
        logger.warning("Digest structure warning: markdown markers are still present")
    if lowered.count("<b>новости</b>") > 1:
        logger.warning("Digest structure warning: multiple news blocks found")
    if "<b>новости</b>" not in lowered:
        logger.warning("Digest structure warning: news block is missing")
    if "<b>итог</b>" not in lowered:
        logger.warning("Digest structure warning: final summary block is missing")

    news_blocks = re.findall(r"<b>\d+\.\s+.+?</b>(.*?)(?=<b>\d+\.\s+|<b>итог</b>|$)", text, flags=re.DOTALL | re.IGNORECASE)
    for index, block in enumerate(news_blocks, start=1):
        missing = [label for label in ("Кратко:", "Почему важно:", "Источник:") if label not in block]
        if missing:
            logger.warning("Digest structure warning: news #%s missing labels: %s", index, ", ".join(missing))


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
            answer = await ask_gigachat(prompt, max_tokens=2600, temperature=0.15)
            return postprocess_digest_html(answer)
        except Exception as exc:
            logger.exception("GigaChat digest request failed, using fallback: %s", exc)
            return self._fallback_digest(items, period_title)

    def _build_digest_prompt(self, items: list[NewsItem], period_title: str) -> str:
        lines = [
            "Ты — редактор персонального новостного дайджеста.",
            "",
            f"Период: {period_title}.",
            "",
            "Сформируй дайджест на русском языке только в формате Telegram-compatible HTML.",
            "Длина ответа: не больше 3300–3600 символов.",
            "Количество новостей: максимум 7–8 главных новостей.",
            "",
            "Жесткие правила форматирования:",
            "1. Используй только HTML, совместимый с Telegram parse_mode='HTML'.",
            "2. Запрещен Markdown: нельзя использовать **, ##, [текст](url), ``` и любые markdown-блоки.",
            "3. Жирный текст оформляй только через <b>...</b>.",
            "4. Цитаты оформляй только через <blockquote>...</blockquote>.",
            "5. Ссылки оформляй только как <a href=\"URL\">Название источника</a>.",
            "6. Не выводи голые URL.",
            "7. Не добавляй второй блок «Новости».",
            "8. Не ставь «Итог» до списка новостей. Итог должен быть только в самом конце.",
            "9. Каждая новость обязательно должна иметь строки «Кратко:», «Почему важно:» и «Источник:».",
            "10. Каждая строка «Кратко» — одно короткое предложение.",
            "11. Каждая строка «Почему важно» — одно короткое предложение.",
            "12. Не делай новости только из заголовка и ссылки.",
            "13. Вводный блок и итог должны быть короткими, без длинных рассуждений.",
            "14. Символы <, >, & в обычном тексте не используй вне разрешенных HTML-тегов.",
            "",
            "Строгий шаблон ответа:",
            f"<b>📰 Дайджест {period_title}</b>",
            "",
            "<blockquote>2–3 предложения: главная суть дайджеста.</blockquote>",
            "",
            "Слоган дайджеста:",
            "<i>Короткий слоган дайджеста одной строкой.</i>",
            "",
            "<b>Новости</b>",
            "",
            "<b>1. Заголовок</b>",
            "Кратко: 1–2 предложения.",
            "Почему важно: 1 предложение.",
            "Источник: <a href=\"URL\">Название источника</a>",
            "",
            "... повтори блок для каждой выбранной новости ...",
            "",
            "<b>Итог</b>",
            "<blockquote>Короткий общий вывод по дайджесту.</blockquote>",
            "",
            "Входные новости:",
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

    async def shorten(self, digest_text: str) -> str:
        prompt = (
            "Сожми этот дайджест до 3000 символов.\n"
            "Сохрани Telegram-compatible HTML-разметку, ссылки и 5–7 главных новостей.\n"
            "Не используй Markdown, ``` и голые URL.\n"
            "Структура должна быть такой же: заголовок, blockquote, слоган, <b>Новости</b>, новости, <b>Итог</b>.\n"
            "Каждая новость должна иметь «Кратко:», «Почему важно:», «Источник:».\n\n"
            f"Дайджест:\n{digest_text}"
        )
        answer = await ask_gigachat(prompt, max_tokens=2200, temperature=0.1)
        return postprocess_digest_html(answer)

    def _fallback_digest(self, items: list[NewsItem], period_title: str) -> str:
        if not items:
            return (
                f"<b>📰 Дайджест {escape(period_title)}</b>\n\n"
                "<blockquote>Подходящих новостей пока не найдено.</blockquote>\n\n"
                "Слоган дайджеста:\n"
                "<i>Сегодня новостная пауза — тоже часть повестки.</i>\n\n"
                "<b>Новости</b>\n\n"
                "<b>Итог</b>\n"
                "<blockquote>Попробуйте выбрать другой период или добавить источники.</blockquote>"
            )

        slogan = self._fallback_slogan(items)
        lines = [
            f"<b>📰 Дайджест {escape(period_title)}</b>",
            "",
            "<blockquote>Собрал свежие новости из выбранных RSS-источников.</blockquote>",
            "",
            "Слоган дайджеста:",
            f"<i>{escape(slogan)}</i>",
            "",
            "<b>Новости</b>",
            "",
        ]
        for index, item in enumerate(items[:12], start=1):
            published = item.published.strftime("%d.%m.%Y") if item.published else "дата не указана"
            source = escape(item.source)
            title = escape(item.title)
            summary = escape(item.summary or "Короткое описание в RSS не указано.")
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
