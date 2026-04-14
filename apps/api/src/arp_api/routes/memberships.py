from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import (
    get_authenticated_actor,
    require_org_access,
    require_project_access,
)
from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz
from arp_core.application import services
from arp_core.contracts.serializers import membership_to_read
from arp_core.contracts.tenant import MembershipCreate, MembershipRead


router = APIRouter(tags=["memberships"])


@router.get("/api/v1/organizations/{org_id}/memberships", response_model=list[MembershipRead])
def list_org_memberships(
    org_id: UUID,
    _: Annotated[authz.OrgAccess, Depends(require_org_access(permission=authz.ensure_org_can_manage_memberships))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[MembershipRead]:
    return [membership_to_read(record) for record in services.list_org_memberships(session, org_id=org_id)]


@router.post(
    "/api/v1/organizations/{org_id}/memberships",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
def create_org_membership(
    org_id: UUID,
    payload: MembershipCreate,
    _: Annotated[authz.OrgAccess, Depends(require_org_access(permission=authz.ensure_org_can_manage_memberships))],
    actor: Annotated[authz.AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MembershipRead:
    membership = services.create_org_membership(
        session,
        org_id=org_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return membership_to_read(membership)


@router.get("/api/v1/projects/{project_id}/memberships", response_model=list[MembershipRead])
def list_project_memberships(
    project_id: UUID,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_manage_memberships)),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[MembershipRead]:
    return [membership_to_read(record) for record in services.list_project_memberships(session, project_id=project_id)]


@router.post(
    "/api/v1/projects/{project_id}/memberships",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_membership(
    project_id: UUID,
    payload: MembershipCreate,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_manage_memberships)),
    ],
    actor: Annotated[authz.AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MembershipRead:
    membership = services.create_project_membership(
        session,
        project_id=project_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return membership_to_read(membership)
