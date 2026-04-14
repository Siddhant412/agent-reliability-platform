from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import get_authenticated_actor
from arp_api.dependencies.db import get_db_session
from arp_core.application import services
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.auth import AuthSessionRead
from arp_core.contracts.serializers import membership_to_read


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me", response_model=AuthSessionRead)
def get_auth_session(
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthSessionRead:
    memberships = services.list_actor_memberships(session, actor=actor)
    return AuthSessionRead(
        user_id=actor.user_id,
        memberships=[membership_to_read(membership) for membership in memberships],
    )
