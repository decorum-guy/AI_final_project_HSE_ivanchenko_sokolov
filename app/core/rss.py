from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser

from app.db.models import NewsSource


logger = logging.getLogger(__name__)
PERIOD_DAYS = {"today": 1, "3days": 3, "week": 7}
PERIOD_TITLES = {"today": "за сегодня", "3days": "за последние 3 дня", "week": "за неделю"}


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str = ""


def period_since(period: str) -> datetime:
    days = PERIOD_DAYS.get(period, 1)
    return datetime.now(timezone.utc) - timedelta(days=days)


def _entry_date(entry) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_source(source: NewsSource, since: datetime) -> list[NewsItem]:
    feed = feedparser.parse(source.rss_url)
    if getattr(feed, "bozo", False):
        logger.warning("RSS parse warning for %s (%s): %s", source.source_id, source.rss_url, getattr(feed, "bozo_exception", "unknown"))
    items: list[NewsItem] = []
    for entry in feed.entries[:30]:
        published = _entry_date(entry)
        if published and published < since:
            continue
        items.append(
            NewsItem(
                title=entry.get("title", "Без заголовка").strip(),
                link=entry.get("link", "").strip(),
                source=source.title,
                published=published,
                summary=entry.get("summary", "").strip(),
            )
        )
    return items


async def fetch_news(sources: list[NewsSource], period: str) -> list[NewsItem]:
    since = period_since(period)
    chunks = await asyncio.gather(*(asyncio.to_thread(_parse_source, source, since) for source in sources), return_exceptions=True)
    items: list[NewsItem] = []
    for chunk in chunks:
        if isinstance(chunk, list):
            items.extend(chunk)
        elif isinstance(chunk, Exception):
            logger.warning("RSS source failed: %s", chunk)
    unique: dict[str, NewsItem] = {}
    for item in items:
        key = item.link or f"{item.source}:{item.title}"
        unique[key] = item
    return sorted(unique.values(), key=lambda item: item.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
