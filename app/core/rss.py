from __future__ import annotations

import asyncio
import logging
import urllib.request
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
    source_id: str
    category: str
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


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _parse_source(source: NewsSource, since: datetime, timeout: int = 10) -> list[NewsItem]:
    try:
        request = urllib.request.Request(source.rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(1024 * 1024)
        feed = feedparser.parse(content)
    except Exception:
        logger.warning("RSS source failed: %s (%s)", source.source_id, source.rss_url, exc_info=True)
        return []

    if getattr(feed, "bozo", False):
        logger.warning("RSS parse warning for %s (%s): %s", source.source_id, source.rss_url, getattr(feed, "bozo_exception", "unknown"))
    if not feed.entries:
        logger.warning("RSS source has empty feed: %s (%s)", source.source_id, source.rss_url)
        return []

    items: list[NewsItem] = []
    for entry in feed.entries[:50]:
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
    total = len(sources)
    found = 0
    items: list[NewsItem] = []
    stats = {
        "sources_selected": total,
        "sources_used": total,
        "articles_collected_before_filtering": 0,
        "articles_after_date_filter": 0,
    }

    for index, source in enumerate(sources, start=1):
        chunk = await asyncio.to_thread(_parse_source, source, since)
        found += len(chunk)
        items.extend(chunk)
        stats["articles_collected_before_filtering"] += len(chunk)
        stats["articles_after_date_filter"] += len(chunk)
        if progress_callback and (index == total or index % 2 == 0):
            await progress_callback(index, total, found)
    return items, stats
