from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from fastapi import Header, Request
from sqlalchemy.orm import Session

from arp_core.persistence.session import SessionManager


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def get_db_session(request: Request) -> Iterator[Session]:
    manager = get_session_manager(request)
    with manager.session() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_actor_user_id(x_actor_user_id: UUID | None = Header(default=None, alias="X-Actor-User-Id")) -> UUID | None:
    return x_actor_user_id
