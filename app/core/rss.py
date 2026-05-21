from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from app.core.rss_fetcher import collect_articles_from_sources
from app.db.models import NewsSource


PERIOD_DAYS = {"today": 1, "3days": 3, "week": 7}
PERIOD_TITLES = {"today": "за сегодня", "3days": "за последние 3 дня", "week": "за неделю"}


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    source_id: str
    category: str
    published: datetime | None
    summary: str = ""


def period_since(period: str) -> datetime:
    days = PERIOD_DAYS.get(period, 1)
    return datetime.now(timezone.utc) - timedelta(days=days)


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    raw = entry.get("published") or entry.get("updated") or entry.get("created")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _items_from_result(source: NewsSource, result: dict, since: datetime) -> list[NewsItem]:
    if result.get("status") == "ERROR":
        return []
    parsed = result.get("parsed")
    entries = list(getattr(parsed, "entries", []) or []) if parsed else []
    items: list[NewsItem] = []
    for entry in entries[:50]:
        published = _entry_date(entry)
        if published and published < since:
            continue
        items.append(
            NewsItem(
                title=_short(entry.get("title", "Без заголовка"), 180),
                link=(entry.get("link") or "").strip(),
                source=source.title,
                source_id=source.source_id,
                category=source.category,
                published=published,
                summary=_short(entry.get("summary", ""), 500),
            )
        )
    return items


async def fetch_news(
    sources: list[NewsSource],
    period: str,
    progress_callback=None,
) -> tuple[list[NewsItem], dict[str, int]]:
    since = period_since(period)
    results = await collect_articles_from_sources(sources, progress_callback=progress_callback)
    by_source_id = {source.source_id: source for source in sources}
    items: list[NewsItem] = []
    for result in results:
        source = by_source_id.get(result["source_id"])
        if not source:
            continue
        items.extend(_items_from_result(source, result, since))

    stats = {
        "sources_selected": len(sources),
        "sources_used": len([result for result in results if result.get("status") in {"OK", "WARNING"}]),
        "articles_collected_before_filtering": sum(result.get("entries_count", 0) for result in results),
        "articles_after_date_filter": len(items),
    }
    return items, stats
