from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.db import get_actor_user_id, get_db_session
from arp_core.application import services
from arp_core.contracts.serializers import project_to_read
from arp_core.contracts.tenant import ProjectCreate, ProjectRead


router = APIRouter(prefix="/api/v1/organizations/{org_id}/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    org_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ProjectRead]:
    return [project_to_read(record) for record in services.list_projects(session, org_id=org_id)]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    org_id: UUID,
    payload: ProjectCreate,
    session: Annotated[Session, Depends(get_db_session)],
    actor_user_id: Annotated[UUID | None, Depends(get_actor_user_id)],
) -> ProjectRead:
    project = services.create_project(session, org_id=org_id, payload=payload, actor_user_id=actor_user_id)
    return project_to_read(project)

