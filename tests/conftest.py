from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from arp_api.main import create_app
from arp_core.persistence.base import Base
from arp_core.persistence.session import SessionManager


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'arp-test.db'}"


@pytest.fixture
def session_manager(sqlite_url: str) -> Iterator[SessionManager]:
    manager = SessionManager(sqlite_url)
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        Base.metadata.drop_all(manager.engine)
        manager.engine.dispose()


@pytest.fixture
def db_session(session_manager: SessionManager) -> Iterator[Session]:
    with session_manager.session() as session:
        yield session
        session.rollback()


@pytest.fixture
def client(sqlite_url: str) -> Iterator[TestClient]:
    app = create_app(database_url=sqlite_url)
    Base.metadata.create_all(app.state.session_manager.engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(app.state.session_manager.engine)
    app.state.session_manager.engine.dispose()

