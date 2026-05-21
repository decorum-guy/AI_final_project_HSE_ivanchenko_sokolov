from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gigachat_client import GigaChatDigestClient
from app.core.recommender import filter_by_interests
from app.core.rss import PERIOD_TITLES, fetch_news
from app.db import queries
from app.db.models import DigestHistory, User


async def build_digest(session: AsyncSession, user: User, source_mode: str, period: str, force_new: bool = False) -> DigestHistory:
    if not force_new:
        cached = await queries.cached_digest(session, user.id, period, source_mode)
        if cached:
            return cached

    sources = await queries.sources_for_user(session, user.id, source_mode)
    items = await fetch_news(sources, period)
    if source_mode == "interests":
        items = filter_by_interests(items, user.interests_text)

    text = await GigaChatDigestClient().summarize(items, PERIOD_TITLES.get(period, "за выбранный период"))
    return await queries.create_digest(
        session=session,
        user_id=user.id,
        text=text,
        period=period,
        source_mode=source_mode,
        used_links=[item.link for item in items if item.link],
    )


async def refresh_digest(session: AsyncSession, user: User, digest: DigestHistory) -> DigestHistory | None:
    sources = await queries.sources_for_user(session, user.id, digest.source_mode)
    items = await fetch_news(sources, digest.period)
    old_links = set((digest.used_links or "").splitlines())
    new_items = [item for item in items if item.link and item.link not in old_links]
    if not new_items:
        return None
    if digest.source_mode == "interests":
        new_items = filter_by_interests(new_items, user.interests_text)
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

