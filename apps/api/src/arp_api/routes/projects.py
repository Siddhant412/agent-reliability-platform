from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import get_authenticated_actor, require_org_access
from arp_api.dependencies.db import get_db_session
from arp_core.application import services
from arp_core.application import auth as authz
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.serializers import project_to_read
from arp_core.contracts.tenant import ProjectCreate, ProjectRead


router = APIRouter(prefix="/api/v1/organizations/{org_id}/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    org_id: UUID,
    access: Annotated[authz.OrgAccess, Depends(require_org_access(permission=lambda access: None))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ProjectRead]:
    projects = services.list_projects(session, org_id=org_id)
    if access.can_view_all_projects():
        return [project_to_read(record) for record in projects]

    visible_project_ids = access.accessible_project_ids()
    return [project_to_read(record) for record in projects if record.id in visible_project_ids]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    org_id: UUID,
    payload: ProjectCreate,
    _: Annotated[authz.OrgAccess, Depends(require_org_access(permission=authz.ensure_org_can_create_project))],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
) -> ProjectRead:
    project = services.create_project(session, org_id=org_id, payload=payload, actor_user_id=actor.user_id)
    return project_to_read(project)
