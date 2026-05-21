from app.config import get_settings
from app.core.rss import NewsItem


class GigaChatDigestClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def summarize(self, items: list[NewsItem], period_title: str) -> str:
        if not self.settings.gigachat_credentials:
            return self._fallback_digest(items, period_title)

        # Здесь можно подключить реальный GigaChat SDK.
        # Для учебного MVP интерфейс не ломается без внешнего API.
        return self._fallback_digest(items, period_title)

    def _fallback_digest(self, items: list[NewsItem], period_title: str) -> str:
        if not items:
            return f"📰 Дайджест {period_title}\n\nПодходящих новостей пока не найдено."
        lines = [f"📰 Дайджест {period_title}", "", "Ключевые новости:"]
        for index, item in enumerate(items[:8], start=1):
            link = f"\n   {item.link}" if item.link else ""
            lines.append(f"{index}. {item.title} — {item.source}{link}")
        lines.append("")
        lines.append("Краткий вывод: это тестовая версия дайджеста из RSS-заголовков. GigaChat можно подключить через GIGACHAT_CREDENTIALS.")
        return "\n".join(lines)

