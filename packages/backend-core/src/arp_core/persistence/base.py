from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime, Uuid
from uuid import UUID, uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


JSON_TYPE = JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")
UUID_TYPE = Uuid(as_uuid=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )


def ensure_sqlite_directory(database_url: str) -> None:
    prefix = "sqlite+pysqlite:///"
    if not database_url.startswith(prefix):
        return
    db_path = database_url.removeprefix(prefix)
    if db_path in {":memory:", ""}:
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
