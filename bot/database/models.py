"""SQLAlchemy ORM models.

Stores the Telegram user, their linked Genshin UID, language preference, arbitrary
settings, and cache metadata. Kept engine-agnostic so the same schema runs on SQLite
(default) or Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class User(Base):
    """A Telegram user and their linked Genshin account + preferences.

    One row per Telegram user. ``genshin_uid`` is nullable until the user links via
    ``/genshinlogin``. Linking is a one-time action; the value persists until logout.
    """

    __tablename__ = "users"

    # Telegram user id is the natural primary key (stable, unique per user).
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Linked Genshin UID (string to preserve leading semantics / server prefix).
    genshin_uid: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    # Preferred language code (e.g. "en", "es", "it", "ja", "zh").
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class UserSetting(Base):
    """Arbitrary per-user key/value settings (feature toggles, display prefs, etc.).

    Kept as a flexible key/value table so new settings can be added without migrations.
    """

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class CacheMeta(Base):
    """Tracks the last time we fetched a given resource for a given key.

    Lets us reason about freshness across restarts (the in-memory response cache is
    volatile; this table is the durable record of "last fetched at").
    """

    __tablename__ = "cache_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)   # e.g. "enka", "akasha"
    key: Mapped[str] = mapped_column(String(64), nullable=False)      # e.g. a UID
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
