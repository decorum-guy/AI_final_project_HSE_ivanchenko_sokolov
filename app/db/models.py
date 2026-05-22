from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    interests_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schedule_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    schedule_day: Mapped[str | None] = mapped_column(String(16), nullable=True)
    silent_notifications: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)

    digests: Mapped[list["DigestHistory"]] = relationship(back_populates="user")


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rss_url: Mapped[str] = mapped_column(Text, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserSource(Base):
    __tablename__ = "user_sources"
    __table_args__ = (UniqueConstraint("user_id", "source_id", name="uq_user_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DigestHistory(Base):
    __tablename__ = "digest_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    digest_text: Mapped[str] = mapped_column(Text)
    digest_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period: Mapped[str] = mapped_column(String(32))
    source_mode: Mapped[str] = mapped_column(String(32))
    source_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    refresh_attempts_left: Mapped[int] = mapped_column(Integer, default=2)
    shorten_attempts_left: Mapped[int] = mapped_column(Integer, default=2)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_links: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="digests")
