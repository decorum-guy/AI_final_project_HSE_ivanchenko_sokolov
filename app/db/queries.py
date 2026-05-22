from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DigestHistory, NewsSource, User, UserSource


logger = logging.getLogger(__name__)
SOURCES_XLSX = Path("app/data/sources.xlsx")
REQUIRED_SOURCE_COLUMNS = {"source_id", "title", "category", "description", "rss_url", "is_active"}

DEFAULT_SOURCES = [
    {
        "source_id": "rbc_tech",
        "title": "РБК Технологии",
        "category": "Технологии",
        "description": "Новости технологий и цифровой экономики",
        "rss_url": "https://rssexport.rbc.ru/rbcnews/technology.rss",
        "is_active": True,
    },
    {
        "source_id": "tass_all",
        "title": "ТАСС",
        "category": "Общество",
        "description": "Главные новости России и мира",
        "rss_url": "https://tass.ru/rss/v2.xml",
        "is_active": True,
    },
    {
        "source_id": "kommersant_news",
        "title": "Коммерсантъ",
        "category": "Бизнес",
        "description": "Главные новости, экономика и политика",
        "rss_url": "https://www.kommersant.ru/RSS/news.xml",
        "is_active": True,
    },
    {
        "source_id": "habr_articles",
        "title": "Хабр",
        "category": "IT",
        "description": "Статьи и новости IT",
        "rss_url": "https://habr.com/ru/rss/articles/",
        "is_active": True,
    },
]


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y", "да", "истина"}


def _read_sources_rows() -> list[dict]:
    if not SOURCES_XLSX.exists():
        logger.warning("sources.xlsx not found, using in-code default sources")
        return DEFAULT_SOURCES

    frame = pd.read_excel(SOURCES_XLSX, engine="openpyxl")
    missing = REQUIRED_SOURCE_COLUMNS - set(frame.columns)
    if missing:
        logger.warning("sources.xlsx misses columns: %s", ", ".join(sorted(missing)))

    rows: list[dict] = []
    for index, row in frame.iterrows():
        source_id = str(row.get("source_id", "")).strip()
        rss_url = str(row.get("rss_url", "")).strip()
        if not source_id or source_id.lower() == "nan" or not rss_url or rss_url.lower() == "nan":
            logger.warning("Skipping source row %s: source_id or rss_url is empty", index + 2)
            continue
        rows.append(
            {
                "source_id": source_id,
                "title": str(row.get("title", source_id)).strip(),
                "category": str(row.get("category", "Без категории")).strip(),
                "description": str(row.get("description", "")).strip(),
                "rss_url": rss_url,
                "is_active": _to_bool(row.get("is_active", True)),
            }
        )
    return rows or DEFAULT_SOURCES


async def sync_sources(session: AsyncSession) -> None:
    """Read sources.xlsx without rewriting it and upsert sources into SQLite."""
    rows = _read_sources_rows()
    current_source_ids = {row["source_id"] for row in rows}

    for row in rows:
        source = await session.scalar(select(NewsSource).where(NewsSource.source_id == row["source_id"]))
        if not source:
            source = NewsSource(**row)
            session.add(source)
            continue
        source.title = row["title"]
        source.category = row["category"]
        source.description = row["description"]
        source.rss_url = row["rss_url"]
        source.is_active = row["is_active"]

    stale_sources = await session.scalars(select(NewsSource).where(NewsSource.source_id.not_in(current_source_ids)))
    stale_count = 0
    for source in stale_sources:
        if source.is_active:
            source.is_active = False
            stale_count += 1
    if stale_count:
        logger.info("Deactivated %s sources missing from sources.xlsx", stale_count)
    await session.commit()


async def seed_sources(session: AsyncSession) -> None:
    await sync_sources(session)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None = None,
    last_name: str | None = None,
    touch: bool = True,
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    now = datetime.utcnow()
    if user:
        changed = False
        if username is not None and user.username != username:
            user.username = username
            changed = True
        if first_name is not None and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if last_name is not None and user.last_name != last_name:
            user.last_name = last_name
            changed = True
        if touch:
            user.last_activity_at = now
            changed = True
        if changed:
            await session.commit()
        return user
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        last_activity_at=now if touch else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def list_sources(session: AsyncSession) -> list[NewsSource]:
    result = await session.scalars(
        select(NewsSource)
        .where(NewsSource.is_active.is_(True), NewsSource.source_id.is_not(None))
        .order_by(NewsSource.category, NewsSource.title)
    )
    return list(result)


async def list_categories(session: AsyncSession) -> list[str]:
    result = await session.scalars(
        select(NewsSource.category)
        .where(NewsSource.is_active.is_(True), NewsSource.source_id.is_not(None))
        .group_by(NewsSource.category)
        .order_by(NewsSource.category)
    )
    return [category for category in result if category]


async def sources_by_category(session: AsyncSession, category: str) -> list[NewsSource]:
    result = await session.scalars(
        select(NewsSource)
        .where(NewsSource.is_active.is_(True), NewsSource.source_id.is_not(None), NewsSource.category == category)
        .order_by(NewsSource.title)
    )
    return list(result)


async def sources_by_ids(session: AsyncSession, source_ids: list[str]) -> list[NewsSource]:
    if not source_ids:
        return []
    result = await session.scalars(
        select(NewsSource)
        .where(NewsSource.source_id.in_(source_ids), NewsSource.is_active.is_(True))
    )
    return list(result)


async def selected_source_ids(session: AsyncSession, user_id: int) -> set[str]:
    result = await session.scalars(select(UserSource.source_id).where(UserSource.user_id == user_id))
    return set(result)


async def selected_sources(session: AsyncSession, user_id: int) -> list[NewsSource]:
    ids = await selected_source_ids(session, user_id)
    if not ids:
        return []
    result = await session.scalars(
        select(NewsSource)
        .where(NewsSource.source_id.in_(ids), NewsSource.is_active.is_(True), NewsSource.source_id.is_not(None))
        .order_by(NewsSource.category, NewsSource.title)
    )
    found = list(result)
    missing = ids - {source.source_id for source in found}
    for source_id in sorted(missing):
        logger.warning("User %s has unknown or inactive source_id subscription: %s", user_id, source_id)
    return found


async def selected_source_signature(session: AsyncSession, user_id: int) -> str:
    ids = await selected_source_ids(session, user_id)
    return "\n".join(sorted(ids))


async def toggle_source(session: AsyncSession, user_id: int, source_id: str) -> bool:
    source = await session.scalar(select(NewsSource).where(NewsSource.source_id == source_id, NewsSource.is_active.is_(True)))
    if not source:
        logger.warning("Cannot toggle unknown or inactive source_id: %s", source_id)
        return False
    link = await session.scalar(select(UserSource).where(UserSource.user_id == user_id, UserSource.source_id == source_id))
    if link:
        await session.delete(link)
        await session.commit()
        return False
    session.add(UserSource(user_id=user_id, source_id=source_id))
    await session.commit()
    return True


async def add_user_sources(session: AsyncSession, user_id: int, source_ids: list[str]) -> int:
    existing = await selected_source_ids(session, user_id)
    added = 0
    for source_id in source_ids:
        if source_id in existing:
            continue
        source = await session.scalar(select(NewsSource).where(NewsSource.source_id == source_id, NewsSource.is_active.is_(True)))
        if not source:
            logger.warning("Cannot add unknown or inactive source_id: %s", source_id)
            continue
        session.add(UserSource(user_id=user_id, source_id=source_id))
        existing.add(source_id)
        added += 1
    if added:
        await session.commit()
    return added


async def sources_for_user(session: AsyncSession, user_id: int, mode: str) -> list[NewsSource]:
    if mode in {"selected_sources", "interests"}:
        selected = await selected_sources(session, user_id)
        return selected
    return await list_sources(session)


async def create_digest(
    session: AsyncSession,
    user_id: int,
    text: str,
    period: str,
    source_mode: str,
    used_links: list[str],
    digest_title: str | None = None,
    source_signature: str | None = None,
) -> DigestHistory:
    digest = DigestHistory(
        user_id=user_id,
        digest_text=text,
        digest_title=digest_title,
        period=period,
        source_mode=source_mode,
        source_signature=source_signature,
        used_links="\n".join(used_links),
    )
    session.add(digest)
    await session.commit()
    await session.refresh(digest)
    return digest


async def get_digest(session: AsyncSession, digest_id: int, user_id: int) -> DigestHistory | None:
    return await session.scalar(select(DigestHistory).where(DigestHistory.id == digest_id, DigestHistory.user_id == user_id))


async def cached_digest(session: AsyncSession, user_id: int, period: str, source_mode: str, source_signature: str | None = None) -> DigestHistory | None:
    conditions = [DigestHistory.user_id == user_id, DigestHistory.period == period, DigestHistory.source_mode == source_mode]
    if source_signature is not None:
        conditions.append(DigestHistory.source_signature == source_signature)
    return await session.scalar(
        select(DigestHistory)
        .where(*conditions)
        .order_by(DigestHistory.created_at.desc())
        .limit(1)
    )


async def history_page(session: AsyncSession, user_id: int, page: int, per_page: int = 5) -> tuple[list[DigestHistory], int]:
    total = await session.scalar(select(func.count(DigestHistory.id)).where(DigestHistory.user_id == user_id)) or 0
    result = await session.scalars(
        select(DigestHistory)
        .where(DigestHistory.user_id == user_id)
        .order_by(DigestHistory.created_at.desc())
        .offset(page * per_page)
        .limit(per_page)
    )
    return list(result), total


async def set_favorite(session: AsyncSession, digest: DigestHistory, value: bool) -> None:
    digest.is_favorite = value
    await session.commit()


async def set_feedback(session: AsyncSession, digest: DigestHistory, feedback: str) -> None:
    digest.feedback = feedback
    digest.feedback_created_at = datetime.utcnow()
    await session.commit()


async def decrement_refresh(session: AsyncSession, digest: DigestHistory) -> None:
    digest.refresh_attempts_left = max(0, digest.refresh_attempts_left - 1)
    await session.commit()


async def decrement_shorten(session: AsyncSession, digest: DigestHistory) -> None:
    attempts_left = digest.shorten_attempts_left if digest.shorten_attempts_left is not None else 2
    digest.shorten_attempts_left = max(0, attempts_left - 1)
    await session.commit()


async def set_llm_provider(session: AsyncSession, user: User, provider: str) -> None:
    user.llm_provider = provider if provider in {"gigachat", "chatgpt"} else "gigachat"
    await session.commit()


async def save_interests(session: AsyncSession, user: User, text: str) -> None:
    user.interests_text = text.strip()
    await session.commit()


async def save_timezone(session: AsyncSession, user: User, timezone: str) -> None:
    user.timezone = timezone
    await session.commit()


async def save_schedule(session: AsyncSession, user: User, schedule_type: str, schedule_time: str, schedule_day: str | None = None) -> None:
    user.schedule_enabled = True
    user.schedule_type = schedule_type
    user.schedule_time = schedule_time
    user.schedule_day = schedule_day if schedule_type == "weekly" else None
    await session.commit()


async def disable_schedule(session: AsyncSession, user: User) -> None:
    user.schedule_enabled = False
    user.schedule_type = None
    user.schedule_time = None
    user.schedule_day = None
    await session.commit()


async def toggle_silent(session: AsyncSession, user: User) -> bool:
    user.silent_notifications = not user.silent_notifications
    await session.commit()
    return user.silent_notifications


async def scheduled_users(session: AsyncSession) -> list[User]:
    result = await session.scalars(select(User).where(User.schedule_enabled.is_(True), User.timezone.is_not(None)))
    return list(result)


async def admin_general_stats(session: AsyncSession) -> dict[str, int]:
    users_count = await session.scalar(select(func.count(User.id))) or 0
    digests_count = await session.scalar(select(func.count(DigestHistory.id))) or 0
    favorite_count = await session.scalar(select(func.count(DigestHistory.id)).where(DigestHistory.is_favorite.is_(True))) or 0
    positive_count = await session.scalar(select(func.count(DigestHistory.id)).where(DigestHistory.feedback == "positive")) or 0
    negative_count = await session.scalar(select(func.count(DigestHistory.id)).where(DigestHistory.feedback == "negative")) or 0
    users_with_sources = await session.scalar(select(func.count(func.distinct(UserSource.user_id)))) or 0
    subscriptions_count = await session.scalar(select(func.count(UserSource.id))) or 0
    return {
        "users_count": users_count,
        "digests_count": digests_count,
        "favorite_count": favorite_count,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "users_with_sources": users_with_sources,
        "subscriptions_count": subscriptions_count,
    }


async def users_page(session: AsyncSession, page: int, per_page: int = 8) -> tuple[list[User], int]:
    total = await session.scalar(select(func.count(User.id))) or 0
    result = await session.scalars(
        select(User)
        .order_by(User.last_activity_at.desc().nullslast(), User.created_at.desc())
        .offset(page * per_page)
        .limit(per_page)
    )
    return list(result), total


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.scalar(select(User).where(User.id == user_id))


async def admin_user_stats(session: AsyncSession, user_id: int) -> dict[str, int]:
    digests_count = await session.scalar(select(func.count(DigestHistory.id)).where(DigestHistory.user_id == user_id)) or 0
    favorite_count = await session.scalar(
        select(func.count(DigestHistory.id)).where(DigestHistory.user_id == user_id, DigestHistory.is_favorite.is_(True))
    ) or 0
    sources_count = await session.scalar(select(func.count(UserSource.id)).where(UserSource.user_id == user_id)) or 0
    positive_count = await session.scalar(
        select(func.count(DigestHistory.id)).where(DigestHistory.user_id == user_id, DigestHistory.feedback == "positive")
    ) or 0
    negative_count = await session.scalar(
        select(func.count(DigestHistory.id)).where(DigestHistory.user_id == user_id, DigestHistory.feedback == "negative")
    ) or 0
    return {
        "digests_count": digests_count,
        "favorite_count": favorite_count,
        "sources_count": sources_count,
        "positive_count": positive_count,
        "negative_count": negative_count,
    }
