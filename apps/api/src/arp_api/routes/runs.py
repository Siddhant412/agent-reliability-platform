from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.db import get_actor_user_id, get_db_session
from arp_core.application import services
from arp_core.contracts.run import RunRead, RunSubmitRequest
from arp_core.contracts.serializers import run_to_read


router = APIRouter(tags=["runs"])


@router.get("/api/v1/projects/{project_id}/runs", response_model=list[RunRead])
def list_runs(
    project_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> list[RunRead]:
    return [run_to_read(record) for record in services.list_runs(session, project_id=project_id)]


@router.post("/api/v1/projects/{project_id}/runs", response_model=RunRead, status_code=status.HTTP_201_CREATED)
def submit_run(
    project_id: UUID,
    payload: RunSubmitRequest,
    session: Annotated[Session, Depends(get_db_session)],
    actor_user_id: Annotated[UUID | None, Depends(get_actor_user_id)],
) -> RunRead:
    run = services.submit_run(session, project_id=project_id, payload=payload, actor_user_id=actor_user_id)
    return run_to_read(run)


@router.get("/api/v1/projects/{project_id}/runs/{run_id}", response_model=RunRead)
def get_run(
    project_id: UUID,
    run_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> RunRead:
    run = services.get_run(session, project_id=project_id, run_id=run_id)
    return run_to_read(run)

