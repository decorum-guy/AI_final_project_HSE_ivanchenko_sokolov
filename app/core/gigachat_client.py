from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import escape
from pathlib import Path
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
OPENAI_USAGE_PATH = Path("logs/openai_usage.json")


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
    response_format: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")

    selected_model = model or _select_openai_model()
    token_limit_parameter = "max_completion_tokens" if selected_model.startswith("gpt-5") else "max_tokens"
    request_payload: dict[str, Any] = {
        "model": selected_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    request_payload[token_limit_parameter] = max_tokens
    openai_response_format = _openai_response_format(response_format)
    if openai_response_format:
        request_payload["response_format"] = openai_response_format

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.error(
                "OpenAI request failed: status=%s model=%s prompt_chars=%s token_param=%s response_preview=%r",
                response.status_code,
                selected_model,
                len(prompt),
                token_limit_parameter,
                response.text[:2000],
            )
            raise
        except httpx.HTTPError as exc:
            logger.error(
                "OpenAI request error: model=%s prompt_chars=%s token_param=%s error=%s",
                selected_model,
                len(prompt),
                token_limit_parameter,
                exc,
            )
            raise
        payload = response.json()
    _record_openai_usage(payload, selected_model)

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("ChatGPT returned an empty response")
    answer = (choices[0].get("message") or {}).get("content", "")
    if not answer:
        raise RuntimeError("ChatGPT returned an empty content")
    return str(answer).strip()


def _today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _read_openai_usage() -> dict[str, Any]:
    if not OPENAI_USAGE_PATH.exists():
        return {"date": _today_key(), "total_tokens": 0, "models": {}}
    try:
        with OPENAI_USAGE_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        logger.warning("Cannot read OpenAI usage file, starting a new daily counter", exc_info=True)
        return {"date": _today_key(), "total_tokens": 0, "models": {}}
    if payload.get("date") != _today_key():
        return {"date": _today_key(), "total_tokens": 0, "models": {}}
    payload.setdefault("total_tokens", 0)
    payload.setdefault("models", {})
    return payload


def _write_openai_usage(payload: dict[str, Any]) -> None:
    try:
        OPENAI_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OPENAI_USAGE_PATH.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
    except Exception:
        logger.warning("Cannot write OpenAI usage file", exc_info=True)


def _select_openai_model() -> str:
    settings = get_settings()
    usage = _read_openai_usage()
    used_tokens = int(usage.get("total_tokens") or 0)
    if settings.openai_daily_token_limit > 0 and used_tokens >= settings.openai_daily_token_limit:
        logger.info(
            "OpenAI daily token limit reached: used=%s limit=%s, switching model from %s to %s",
            used_tokens,
            settings.openai_daily_token_limit,
            settings.openai_model,
            settings.openai_fallback_model,
        )
        return settings.openai_fallback_model
    return settings.openai_model


def _record_openai_usage(payload: dict[str, Any], model: str) -> None:
    usage = payload.get("usage") or {}
    total_tokens = int(usage.get("total_tokens") or 0)
    if total_tokens <= 0:
        logger.debug("OpenAI response has no usage.total_tokens, usage=%s", usage)
        return

    daily_usage = _read_openai_usage()
    daily_usage["total_tokens"] = int(daily_usage.get("total_tokens") or 0) + total_tokens
    models = daily_usage.setdefault("models", {})
    models[model] = int(models.get(model) or 0) + total_tokens
    _write_openai_usage(daily_usage)
    logger.info(
        "OpenAI usage recorded: model=%s request_tokens=%s daily_tokens=%s",
        model,
        total_tokens,
        daily_usage["total_tokens"],
    )


def _openai_response_format(response_format: dict[str, Any] | None) -> dict[str, Any] | None:
    if not response_format:
        return None
    if response_format.get("type") == "json_schema":
        schema = response_format.get("schema")
        if not isinstance(schema, dict):
            return None
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_format.get("name") or "structured_response",
                "schema": schema,
                "strict": bool(response_format.get("strict", True)),
            },
        }
    if response_format.get("type") == "json_object":
        return {"type": "json_object"}
    return None


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
        return await ask_chatgpt(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            response_format=response_format,
        )
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
    text = _normalize_digest_structure(text)
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
    return _normalize_digest_structure(text)


def _normalize_digest_structure(text: str) -> str:
    text = re.sub(
        r"(?ims)^\s*Слоган дайджеста\s*:\s*\n?\s*(?:<i>.*?</i>|.+?)\s*(?=\n\s*<b>(?:Новости|Подробно)</b>)",
        "",
        text,
    )
    text = re.sub(r"(?i)<b>\s*Новости\s*</b>", "<b>Подробно</b>", text)
    text = re.sub(r"(?m)^Кратко:\s*", "<b>Кратко:</b> ", text)
    text = re.sub(r"(?m)^Почему важно:\s*", "<b>Почему важно:</b> ", text)
    return text.strip()


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
    news_index = text.lower().find("<b>подробно</b>")
    summary_index = text.lower().find("<b>итог</b>")
    return summary_index != -1 and (news_index == -1 or summary_index < news_index)


def _log_digest_quality(text: str) -> None:
    lowered = text.lower()
    if "```" in text or "##" in text or re.search(r"\[[^\]]+]\(https?://", text):
        logger.warning("Digest structure warning: markdown markers are still present")
    if "слоган дайджеста" in lowered:
        logger.warning("Digest structure warning: slogan block is still present")
    if lowered.count("<b>подробно</b>") > 1:
        logger.warning("Digest structure warning: multiple details blocks found")
    if "<b>подробно</b>" not in lowered:
        logger.warning("Digest structure warning: details block is missing")
    if "<b>итог</b>" not in lowered:
        logger.warning("Digest structure warning: final summary block is missing")

    news_blocks = re.findall(r"<b>\d+\.\s+.+?</b>(.*?)(?=<b>\d+\.\s+|<b>итог</b>|$)", text, flags=re.DOTALL | re.IGNORECASE)
    for index, block in enumerate(news_blocks, start=1):
        missing = [label for label in ("<b>Кратко:</b>", "<b>Почему важно:</b>", "Источник:") if label not in block]
        if missing:
            logger.warning("Digest structure warning: news #%s missing labels: %s", index, ", ".join(missing))


class GigaChatDigestClient:
    def __init__(self, provider: str | None = None) -> None:
        self.settings = get_settings()
        self.provider = (provider or self.settings.ai_provider or "gigachat").lower()

    async def summarize(self, items: list[NewsItem], period_title: str) -> str:
        if self.provider == "gigachat" and not self.settings.gigachat_credentials:
            logger.warning("GIGACHAT_CREDENTIALS is empty, using fallback digest")
            return repair_digest_text(self._fallback_digest(items, period_title))
        if self.provider == "chatgpt" and not self.settings.openai_api_key:
            logger.warning("OPENAI_API_KEY is empty, using fallback digest")
            return repair_digest_text(self._fallback_digest(items, period_title))

        prompt = self._build_digest_prompt(items, period_title)
        logger.info("Sending digest prompt to AI provider: provider=%s items=%s chars=%s", self.provider, len(items), len(prompt))
        try:
            answer = await ask_llm(prompt, provider=self.provider, max_tokens=2600, temperature=0.15)
            text = postprocess_digest_html(answer)
            return repair_digest_text(text)
        except Exception as exc:
            logger.exception("AI digest request failed, using fallback: %s", exc)
            return repair_digest_text(self._fallback_digest(items, period_title))

    def _build_digest_prompt(self, items: list[NewsItem], period_title: str) -> str:
        lines = [
            "Ты — редактор персонального новостного дайджеста.",
            "",
            f"Период: {period_title}.",
            "",
            "Сформируй короткий дайджест на русском языке только в формате Telegram-compatible HTML.",
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
            "7. Не используй слово «Новости» как отдельный заголовок блока. Вместо него всегда используй <b>Подробно</b>.",
            "8. Не добавляй слоган и не используй строку «Слоган дайджеста».",
            "9. Не ставь «Итог» до списка новостей. Итог должен быть только в самом конце.",
            "10. Каждая новость обязательно должна иметь строки <b>Кратко:</b>, <b>Почему важно:</b> и Источник:.",
            "11. Каждая строка <b>Кратко:</b> — одно короткое предложение.",
            "12. Каждая строка <b>Почему важно:</b> — одно короткое предложение.",
            "13. Не делай новости только из заголовка и ссылки.",
            "14. Вводный блок и итог должны быть короткими, без длинных рассуждений.",
            "15. Символы <, >, & в обычном тексте не используй вне разрешенных HTML-тегов.",
            "16. Не копируй поясняющие строки шаблона. Вместо описаний из шаблона всегда пиши реальный текст.",
            "",
            "Строгий шаблон ответа:",
            f"<b>📰 Дайджест {period_title}</b>",
            "",
            "<b>Очень кратко</b>",
            "<blockquote>Главные события периода в двух коротких предложениях.</blockquote>",
            "",
            "<b>Подробно</b>",
            "",
            "<b>1. Заголовок</b>",
            "<b>Кратко:</b> 1 короткое предложение.",
            "<b>Почему важно:</b> 1 короткое предложение.",
            "Источник: <a href=\"URL\">Название источника</a>",
            "",
            "<b>2. Следующая новость</b>",
            "<b>Кратко:</b> 1 короткое предложение.",
            "<b>Почему важно:</b> 1 короткое предложение.",
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
            "Структура должна быть такой: заголовок, <b>Очень кратко</b>, blockquote, <b>Подробно</b>, новости, <b>Итог</b>.\n"
            "Не добавляй слоган и не используй заголовок «Новости».\n"
            "Каждая новость должна иметь <b>Кратко:</b>, <b>Почему важно:</b>, Источник:.\n\n"
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
                "<b>Очень кратко</b>\n"
                "<blockquote>Подходящих новостей пока не найдено.</blockquote>\n\n"
                "<b>Подробно</b>\n\n"
                "<b>Итог</b>\n"
                "<blockquote>Попробуйте выбрать другой период или добавить источники.</blockquote>"
            )

        lines = [
            f"<b>📰 Дайджест {escape(period_title)}</b>",
            "",
            "<b>Очень кратко</b>",
            "<blockquote>Резервная версия сформирована автоматически по выбранным RSS-источникам.</blockquote>",
            "",
            "<b>Подробно</b>",
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
                    f"<b>Кратко:</b> {summary}",
                    f"<b>Почему важно:</b> материал относится к выбранной повестке за период, дата: {escape(published)}.",
                    source_line,
                    "",
                ]
            )
        lines.append("<b>Итог</b>")
        lines.append("<blockquote>Резервная версия сформирована автоматически, потому что ИИ-сервис временно недоступен.</blockquote>")
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
