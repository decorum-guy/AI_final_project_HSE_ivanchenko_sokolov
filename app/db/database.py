from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.execute(text("PRAGMA table_info(users)"))
        existing = {row[1] for row in columns}
        migrations = {
            "first_name": "ALTER TABLE users ADD COLUMN first_name VARCHAR(255)",
            "last_name": "ALTER TABLE users ADD COLUMN last_name VARCHAR(255)",
            "last_activity_at": "ALTER TABLE users ADD COLUMN last_activity_at DATETIME",
            "schedule_day": "ALTER TABLE users ADD COLUMN schedule_day VARCHAR(16)",
            "llm_provider": "ALTER TABLE users ADD COLUMN llm_provider VARCHAR(32)",
            "interests_keywords": "ALTER TABLE users ADD COLUMN interests_keywords TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing:
                await conn.execute(text(statement))
        source_columns = await conn.execute(text("PRAGMA table_info(news_sources)"))
        existing_source_columns = {row[1] for row in source_columns}
        if "source_id" not in existing_source_columns:
            await conn.execute(text("ALTER TABLE news_sources ADD COLUMN source_id VARCHAR(128)"))
        digest_columns = await conn.execute(text("PRAGMA table_info(digest_history)"))
        existing_digest_columns = {row[1] for row in digest_columns}
        if "shorten_attempts_left" not in existing_digest_columns:
            await conn.execute(text("ALTER TABLE digest_history ADD COLUMN shorten_attempts_left INTEGER DEFAULT 2"))
        if "digest_title" not in existing_digest_columns:
            await conn.execute(text("ALTER TABLE digest_history ADD COLUMN digest_title VARCHAR(120)"))
        if "source_signature" not in existing_digest_columns:
            await conn.execute(text("ALTER TABLE digest_history ADD COLUMN source_signature TEXT"))
