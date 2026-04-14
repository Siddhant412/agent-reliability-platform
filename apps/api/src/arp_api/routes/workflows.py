from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.db import get_actor_user_id, get_db_session
from arp_core.application import services
from arp_core.contracts.serializers import workflow_to_read, workflow_version_to_read
from arp_core.contracts.workflow import (
    PublishWorkflowVersionRequest,
    WorkflowCreate,
    WorkflowRead,
    WorkflowVersionCreate,
    WorkflowVersionRead,
)


router = APIRouter(tags=["workflows"])


@router.get("/api/v1/projects/{project_id}/workflows", response_model=list[WorkflowRead])
def list_workflows(
    project_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> list[WorkflowRead]:
    return [workflow_to_read(record) for record in services.list_workflows(session, project_id=project_id)]


@router.post("/api/v1/projects/{project_id}/workflows", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
def create_workflow(
    project_id: UUID,
    payload: WorkflowCreate,
    session: Annotated[Session, Depends(get_db_session)],
    actor_user_id: Annotated[UUID | None, Depends(get_actor_user_id)],
) -> WorkflowRead:
    workflow = services.create_workflow(session, project_id=project_id, payload=payload, actor_user_id=actor_user_id)
    return workflow_to_read(workflow)


@router.get("/api/v1/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionRead])
def list_workflow_versions(
    workflow_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> list[WorkflowVersionRead]:
    return [
        workflow_version_to_read(record)
        for record in services.list_workflow_versions(session, workflow_id=workflow_id)
    ]


@router.post(
    "/api/v1/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_version(
    workflow_id: UUID,
    payload: WorkflowVersionCreate,
    session: Annotated[Session, Depends(get_db_session)],
    actor_user_id: Annotated[UUID | None, Depends(get_actor_user_id)],
) -> WorkflowVersionRead:
    version = services.create_workflow_version(
        session,
        workflow_id=workflow_id,
        payload=payload,
        actor_user_id=actor_user_id,
    )
    return workflow_version_to_read(version)


@router.post("/api/v1/workflow-versions/{workflow_version_id}/publish", response_model=WorkflowVersionRead)
def publish_workflow_version(
    workflow_version_id: UUID,
    payload: PublishWorkflowVersionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    actor_user_id: Annotated[UUID | None, Depends(get_actor_user_id)],
) -> WorkflowVersionRead:
    version = services.publish_workflow_version(
        session,
        workflow_version_id=workflow_version_id,
        payload=payload,
        actor_user_id=actor_user_id,
    )
    return workflow_version_to_read(version)

