from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.db import get_actor_user_id, get_db_session
from arp_core.application import services
from arp_core.contracts.serializers import organization_to_read
from arp_core.contracts.tenant import OrganizationCreate, OrganizationRead


router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationRead])
def list_organizations(session: Annotated[Session, Depends(get_db_session)]) -> list[OrganizationRead]:
    return [organization_to_read(record) for record in services.list_organizations(session)]


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    session: Annotated[Session, Depends(get_db_session)],
    actor_user_id: Annotated[UUID | None, Depends(get_actor_user_id)],
) -> OrganizationRead:
    organization = services.create_organization(session, payload, actor_user_id=actor_user_id)
    return organization_to_read(organization)

