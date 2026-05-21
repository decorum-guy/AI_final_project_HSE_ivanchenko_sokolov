from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gigachat_client import GigaChatDigestClient, repair_digest_text
from app.core.recommender import filter_by_interests, relevance_score
from app.core.rss import PERIOD_TITLES, NewsItem, fetch_news
from app.db import queries
from app.db.models import DigestHistory, User


logger = logging.getLogger(__name__)
MAX_SOURCES_PER_DIGEST = 12
MAX_ARTICLES_PER_SOURCE = {"today": 3, "3days": 4, "week": 5}
MAX_TOTAL_ARTICLES = {"today": 25, "3days": 35, "week": 45}
MAX_LLM_ARTICLES = 8
MIN_TODAY_ARTICLES = 5


@dataclass(frozen=True)
class PreparedDigestInput:
    items: list[NewsItem]
    used_links: list[str]
    note: str | None
    stats: dict[str, int]


def _normalize_title(title: str) -> str:
    return " ".join(re.findall(r"[a-zA-Zа-яА-Я0-9]+", title.lower()))


def _deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    result: list[NewsItem] = []
    for item in items:
        link_key = item.link.strip().lower()
        title_key = _normalize_title(item.title)
        if link_key and link_key in seen_links:
            continue
        if title_key and title_key in seen_titles:
            continue
        if link_key:
            seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)
        result.append(item)
    return result


def _limit_per_source(items: list[NewsItem], period: str) -> list[NewsItem]:
    limit = MAX_ARTICLES_PER_SOURCE.get(period, 3)
    counters: dict[str, int] = defaultdict(int)
    result: list[NewsItem] = []
    for item in items:
        if counters[item.source_id] >= limit:
            continue
        counters[item.source_id] += 1
        result.append(item)
    return result


async def prepare_digest_input(
    session: AsyncSession,
    user: User,
    source_mode: str,
    period: str,
    progress_callback=None,
) -> PreparedDigestInput:
    selected_sources = await queries.sources_for_user(session, user.id, source_mode)
    sources = selected_sources[:MAX_SOURCES_PER_DIGEST]

    fetch_period = period
    note = None
    items, fetch_stats = await fetch_news(sources, fetch_period, progress_callback=progress_callback)
    if period == "today" and len(items) < MIN_TODAY_ARTICLES:
        note = "За сегодня найдено мало материалов, поэтому я добавил свежие новости за последние 3 дня."
        fetch_period = "3days"
        items, fetch_stats = await fetch_news(sources, fetch_period, progress_callback=progress_callback)

    collected = len(items)
    deduped = _deduplicate(items)
    if source_mode == "interests":
        deduped = filter_by_interests(deduped, user.interests_text)
    else:
        deduped = sorted(deduped, key=lambda item: (item.published is not None, item.published or datetime.min), reverse=True)

    limited_per_source = _limit_per_source(deduped, period)
    ranked = sorted(
        limited_per_source,
        key=lambda item: (
            relevance_score(f"{item.title} {item.summary} {item.source} {item.category}", user.interests_text),
            item.published is not None,
            item.published or datetime.min,
        ),
        reverse=True,
    )
    total_limit = min(MAX_TOTAL_ARTICLES.get(period, 25), MAX_LLM_ARTICLES)
    final_items = ranked[:total_limit]

    stats = {
        "sources_selected": len(selected_sources),
        "sources_used": len(sources),
        "articles_collected_before_filtering": fetch_stats.get("articles_collected_before_filtering", collected),
        "articles_after_date_filter": fetch_stats.get("articles_after_date_filter", collected),
        "articles_after_deduplication": len(deduped),
        "articles_sent_to_llm": len(final_items),
    }
    logger.info(
        "Digest input prepared: mode=%s period=%s sources selected=%s sources used=%s "
        "articles collected before filtering=%s articles after date filter=%s "
        "articles after deduplication=%s articles sent to LLM=%s",
        source_mode,
        period,
        stats["sources_selected"],
        stats["sources_used"],
        stats["articles_collected_before_filtering"],
        stats["articles_after_date_filter"],
        stats["articles_after_deduplication"],
        stats["articles_sent_to_llm"],
    )
    return PreparedDigestInput(
        items=final_items,
        used_links=[item.link for item in final_items if item.link],
        note=note,
        stats=stats,
    )


async def build_digest(
    session: AsyncSession,
    user: User,
    source_mode: str,
    period: str,
    force_new: bool = False,
    progress_callback=None,
) -> DigestHistory:
    if not force_new:
        cached = await queries.cached_digest(session, user.id, period, source_mode)
        if cached:
            repaired = repair_digest_text(cached.digest_text)
            if repaired != cached.digest_text:
                cached.digest_text = repaired
                await session.commit()
                await session.refresh(cached)
            return cached

    prepared = await prepare_digest_input(session, user, source_mode, period, progress_callback=progress_callback)
    if not prepared.items:
        text = "Не удалось найти свежие новости по выбранным источникам за этот период. Попробуйте выбрать другой период или добавить источники."
    else:
        text = await GigaChatDigestClient().summarize(prepared.items, PERIOD_TITLES.get(period, "за выбранный период"))
        if prepared.note:
            text = f"{prepared.note}\n\n{text}"

    return await queries.create_digest(
        session=session,
        user_id=user.id,
        text=text,
        period=period,
        source_mode=source_mode,
        used_links=prepared.used_links,
    )


async def refresh_digest(session: AsyncSession, user: User, digest: DigestHistory) -> DigestHistory | None:
    prepared = await prepare_digest_input(session, user, digest.source_mode, digest.period)
    old_links = set((digest.used_links or "").splitlines())
    new_items = [item for item in prepared.items if item.link and item.link not in old_links]
    if not new_items:
        return None
    text = await GigaChatDigestClient().summarize(new_items, PERIOD_TITLES.get(digest.period, "за выбранный период"))
    return await queries.create_digest(
        session=session,
        user_id=user.id,
        text=text,
        period=digest.period,
        source_mode=digest.source_mode,
        used_links=[item.link for item in new_items if item.link],
    )
