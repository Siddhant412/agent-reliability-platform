from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from arp_core.persistence.base import ensure_sqlite_directory


class SessionManager:
    def __init__(self, database_url: str):
        engine_kwargs: dict[str, object] = {"future": True}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        ensure_sqlite_directory(database_url)
        self.engine: Engine = create_engine(database_url, **engine_kwargs)
        self._session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()
