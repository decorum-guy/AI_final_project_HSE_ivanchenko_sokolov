from __future__ import annotations

import logging
import re
from datetime import datetime
from html import escape
from typing import Any

import httpx

from app.config import get_settings
from app.core.rss import NewsItem


logger = logging.getLogger(__name__)

ALLOWED_TAG_RE = re.compile(r"</?(?:b|i|blockquote)>|<a\s+href=\"[^\"]+\">|</a>", re.IGNORECASE)
MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)\)")
SLOGAN_PLACEHOLDERS = (
    "Короткий слоган дайджеста одной строкой.",
    "Короткий слоган дайджеста в одну строку.",
    "Конкретный короткий слоган по темам новостей.",
)


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


async def ask_chatgpt(
    prompt: str,
    *,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    model: str | None = None,
) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or settings.openai_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        payload = response.json()

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("ChatGPT returned an empty response")
    answer = (choices[0].get("message") or {}).get("content", "")
    if not answer:
        raise RuntimeError("ChatGPT returned an empty content")
    return str(answer).strip()


async def ask_llm(
    prompt: str,
    *,
    provider: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    model: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    selected = (provider or get_settings().ai_provider or "gigachat").lower()
    if selected == "chatgpt":
        return await ask_chatgpt(prompt, max_tokens=max_tokens, temperature=temperature, model=model)
    return await ask_gigachat(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        model=model,
        response_format=response_format,
    )


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
    text = _remove_prompt_leaks(text)
    text = _ensure_slogan_label(text)
    text = sanitize_telegram_html(text)

    if "**" in text:
        logger.warning("Digest post-processing left markdown bold markers in text")
    if _has_early_summary(text):
        logger.warning("Digest structure warning: итог appears before новости")
    _log_digest_quality(text)
    return text


def _remove_prompt_leaks(text: str) -> str:
    blocked_patterns = (
        r"^\s*important\s*:.*$",
        r"^\s*важно\s*:.*$",
        r"^\s*строго следуй.*$",
        r"^\s*не копируй.*$",
        r"^\s*сохрани telegram-compatible.*$",
    )
    lines = []
    for line in text.splitlines():
        normalized = line.strip().lower()
        if any(re.match(pattern, normalized, flags=re.IGNORECASE) for pattern in blocked_patterns):
            logger.warning("Removed leaked prompt instruction from digest: %s", line[:120])
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _ensure_slogan_label(text: str) -> str:
    if re.search(r"(?im)^\s*Слоган дайджеста\s*:", text):
        return text

    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        plain = re.sub(r"</?i>", "", stripped, flags=re.IGNORECASE).strip()
        if plain in SLOGAN_PLACEHOLDERS:
            lines.insert(index, "Слоган дайджеста:")
            return "\n".join(lines)
        if stripped.lower().startswith("<i>") and stripped.lower().endswith("</i>"):
            previous = "\n".join(lines[max(0, index - 3) : index]).lower()
            following = "\n".join(lines[index + 1 : index + 4]).lower()
            if "<blockquote>" in previous and "<b>новости</b>" in following:
                lines.insert(index, "Слоган дайджеста:")
                return "\n".join(lines)
    return text


def repair_digest_text(text: str) -> str:
    for placeholder in SLOGAN_PLACEHOLDERS:
        text = text.replace(placeholder, _fallback_slogan_from_text(text))
    return _ensure_slogan_label(text)


def _has_slogan_placeholder(text: str) -> bool:
    return any(placeholder in text for placeholder in SLOGAN_PLACEHOLDERS)


def _fallback_slogan_from_text(text: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if "спорт" in plain.lower() and ("игр" in plain.lower() or "технолог" in plain.lower()):
        return "Спорт, игры и технологии задают темп сегодняшней повестке."
    if "технолог" in plain.lower() or "github" in plain.lower() or "amd" in plain.lower():
        return "Технологическая повестка сегодня держит высокий темп."
    if "игр" in plain.lower() or "steam" in plain.lower():
        return "Игровая индустрия снова подбрасывает громкие поводы."
    return "Главные события дня — коротко, по делу и без лишнего шума."


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
    def __init__(self, provider: str | None = None) -> None:
        self.settings = get_settings()
        self.provider = (provider or self.settings.ai_provider or "gigachat").lower()

    async def summarize(self, items: list[NewsItem], period_title: str) -> str:
        if self.provider == "gigachat" and not self.settings.gigachat_credentials:
            logger.warning("GIGACHAT_CREDENTIALS is empty, using fallback digest")
            return self._fallback_digest(items, period_title)
        if self.provider == "chatgpt" and not self.settings.openai_api_key:
            logger.warning("OPENAI_API_KEY is empty, using fallback digest")
            return self._fallback_digest(items, period_title)

        prompt = self._build_digest_prompt(items, period_title)
        logger.info("Sending digest prompt to GigaChat: items=%s chars=%s", len(items), len(prompt))
        try:
            answer = await ask_llm(prompt, provider=self.provider, max_tokens=2600, temperature=0.15)
            text = postprocess_digest_html(answer)
            if _has_slogan_placeholder(text):
                logger.warning("GigaChat copied digest slogan placeholder; regenerating slogan")
                text = await self._replace_placeholder_slogan(text)
            return repair_digest_text(text)
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
            "15. Не копируй поясняющие строки шаблона. Вместо описаний из шаблона всегда пиши реальный текст.",
            "16. Обязательно оставь отдельную строку «Слоган дайджеста:» перед строкой со слоганом.",
            "17. Слоган пиши на следующей строке после «Слоган дайджеста:» и оформляй его через <i>...</i>.",
            "",
            "Строгий шаблон ответа:",
            f"<b>📰 Дайджест {period_title}</b>",
            "",
            "<blockquote>Главная суть дайджеста в двух коротких предложениях.</blockquote>",
            "",
            "Слоган дайджеста:",
            "<i>Конкретный короткий слоган по темам новостей.</i>",
            "",
            "<b>Новости</b>",
            "",
            "<b>1. Заголовок</b>",
            "Кратко: 1–2 предложения.",
            "Почему важно: 1 предложение.",
            "Источник: <a href=\"URL\">Название источника</a>",
            "",
            "<b>2. Следующая новость</b>",
            "Кратко: 1–2 предложения.",
            "Почему важно: 1 предложение.",
            "Источник: <a href=\"URL\">Название источника</a>",
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

    async def _replace_placeholder_slogan(self, digest_text: str) -> str:
        prompt = (
            "Придумай один короткий слоган на русском языке для этого новостного дайджеста.\n"
            "Правила: одна строка, до 80 символов, без кавычек, без Markdown, без HTML, без пояснений.\n\n"
            f"Дайджест:\n{digest_text[:3500]}"
        )
        try:
            slogan = await ask_llm(prompt, provider=self.provider, max_tokens=120, temperature=0.4)
            slogan = re.sub(r"<[^>]+>", "", slogan).strip().strip('"').strip("'")
            slogan = re.sub(r"\s+", " ", slogan)
            if not slogan or len(slogan) > 120:
                slogan = _fallback_slogan_from_text(digest_text)
        except Exception:
            slogan = _fallback_slogan_from_text(digest_text)

        for placeholder in SLOGAN_PLACEHOLDERS:
            digest_text = digest_text.replace(placeholder, escape(slogan))
        return digest_text

    async def shorten(self, digest_text: str) -> str:
        prompt = (
            "Сожми этот дайджест до 3000 символов.\n"
            "Сохрани Telegram-compatible HTML-разметку, ссылки и 5–7 главных новостей.\n"
            "Не используй Markdown, ``` и голые URL.\n"
            "Структура должна быть такой же: заголовок, blockquote, слоган, <b>Новости</b>, новости, <b>Итог</b>.\n"
            "Каждая новость должна иметь «Кратко:», «Почему важно:», «Источник:».\n\n"
            f"Дайджест:\n{digest_text}"
        )
        answer = await ask_llm(prompt, provider=self.provider, max_tokens=2200, temperature=0.1)
        return postprocess_digest_html(answer)

    async def history_title(self, digest_text: str) -> str:
        prompt = (
            "Придумай короткое название для истории новостного дайджеста.\n"
            "Правила: 3–6 слов, без кавычек, без Markdown, без HTML, без точки в конце.\n\n"
            f"Дайджест:\n{digest_text[:2500]}"
        )
        try:
            title = await ask_llm(prompt, provider=self.provider, max_tokens=80, temperature=0.3)
            title = re.sub(r"<[^>]+>", "", title).strip().strip('"').strip("'")
            title = re.sub(r"\s+", " ", title)
            if not title or len(title) > 80:
                return "Свежая подборка новостей"
            return title
        except Exception:
            logger.exception("Failed to generate digest history title")
            return "Свежая подборка новостей"

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
