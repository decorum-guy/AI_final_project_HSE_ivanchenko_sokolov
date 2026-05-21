from __future__ import annotations

import logging
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
) -> str:
    settings = get_settings()
    if not settings.gigachat_credentials:
        raise RuntimeError("GIGACHAT_CREDENTIALS is empty")

    from gigachat import GigaChat
    from gigachat.models import Chat, Messages, MessagesRole

    payload = Chat(
        model=model,
        messages=[Messages(role=MessagesRole.USER, content=prompt)],
        max_tokens=max_tokens,
        temperature=temperature,
    )

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
            "Составь короткий структурированный дайджест на русском языке.",
            "Правила:",
            "1. Не придумывай факты, используй только переданные новости.",
            "2. Сгруппируй новости по смыслу, если это уместно.",
            "3. Для каждой важной новости дай 1-2 предложения и ссылку.",
            "4. В конце добавь краткий вывод.",
            "5. Не пиши, что ты языковая модель.",
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
            return f"📰 Дайджест {period_title}\n\nПодходящих новостей пока не найдено."
        lines = [f"📰 Дайджест {period_title}", "", "Ключевые новости:"]
        for index, item in enumerate(items[:12], start=1):
            published = item.published.strftime("%d.%m.%Y") if item.published else "дата не указана"
            link = f"\n   {item.link}" if item.link else ""
            lines.append(f"{index}. {item.title} — {item.source}, {published}{link}")
        lines.append("")
        lines.append("Краткий вывод: это резервная версия дайджеста из RSS-заголовков, потому что GigaChat сейчас недоступен.")
        return "\n".join(lines)
