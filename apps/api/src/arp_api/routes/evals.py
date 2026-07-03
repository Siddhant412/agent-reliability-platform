from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import get_authenticated_actor, require_project_access
from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz
from arp_core.application import services
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.eval import (
    DatasetCreate,
    DatasetRead,
    EvalCaseCreate,
    EvalCaseRead,
    EvalCaseResultRead,
    EvalRunCreate,
    EvalRunRead,
)
from arp_core.contracts.serializers import (
    dataset_to_read,
    eval_case_result_to_read,
    eval_case_to_read,
    eval_run_to_read,
)
from arp_worker.evals import execute_eval_run


router = APIRouter(tags=["evals"])


@router.get("/api/v1/projects/{project_id}/datasets", response_model=list[DatasetRead])
def list_datasets(
    project_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[DatasetRead]:
    return [dataset_to_read(record) for record in services.list_datasets(session, project_id=project_id)]


@router.post(
    "/api/v1/projects/{project_id}/datasets",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset(
    project_id: UUID,
    payload: DatasetCreate,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_write_workflows)),
    ],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DatasetRead:
    dataset = services.create_dataset(
        session,
        project_id=project_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return dataset_to_read(dataset)


@router.get("/api/v1/projects/{project_id}/datasets/{dataset_id}/cases", response_model=list[EvalCaseRead])
def list_eval_cases(
    project_id: UUID,
    dataset_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[EvalCaseRead]:
    return [
        eval_case_to_read(record)
        for record in services.list_eval_cases(session, project_id=project_id, dataset_id=dataset_id)
    ]


@router.post(
    "/api/v1/projects/{project_id}/datasets/{dataset_id}/cases",
    response_model=EvalCaseRead,
    status_code=status.HTTP_201_CREATED,
)
def create_eval_case(
    project_id: UUID,
    dataset_id: UUID,
    payload: EvalCaseCreate,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_write_workflows)),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> EvalCaseRead:
    eval_case = services.create_eval_case(
        session,
        project_id=project_id,
        dataset_id=dataset_id,
        payload=payload,
    )
    return eval_case_to_read(eval_case)


@router.get("/api/v1/projects/{project_id}/eval-runs", response_model=list[EvalRunRead])
def list_eval_runs(
    project_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[EvalRunRead]:
    return [eval_run_to_read(record) for record in services.list_eval_runs(session, project_id=project_id)]


@router.post(
    "/api/v1/projects/{project_id}/eval-runs",
    response_model=EvalRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_eval_run(
    project_id: UUID,
    payload: EvalRunCreate,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_write_workflows)),
    ],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> EvalRunRead:
    eval_run = services.create_eval_run(
        session,
        project_id=project_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return eval_run_to_read(eval_run)


@router.get("/api/v1/projects/{project_id}/eval-runs/{eval_run_id}", response_model=EvalRunRead)
def get_eval_run(
    project_id: UUID,
    eval_run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> EvalRunRead:
    return eval_run_to_read(services.get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id))


@router.post("/api/v1/projects/{project_id}/eval-runs/{eval_run_id}/execute", response_model=EvalRunRead)
def execute_eval(
    project_id: UUID,
    eval_run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
) -> EvalRunRead:
    execute_eval_run(session, project_id=project_id, eval_run_id=eval_run_id)
    return eval_run_to_read(services.get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id))


@router.post("/api/v1/projects/{project_id}/eval-runs/{eval_run_id}/enqueue", response_model=EvalRunRead)
def enqueue_eval(
    project_id: UUID,
    eval_run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> EvalRunRead:
    eval_run = services.enqueue_eval_run(
        session,
        project_id=project_id,
        eval_run_id=eval_run_id,
        actor_user_id=actor.user_id,
    )
    return eval_run_to_read(eval_run)


@router.get(
    "/api/v1/projects/{project_id}/eval-runs/{eval_run_id}/results",
    response_model=list[EvalCaseResultRead],
)
def list_eval_results(
    project_id: UUID,
    eval_run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[EvalCaseResultRead]:
    return [
        eval_case_result_to_read(record)
        for record in services.list_eval_case_results(session, project_id=project_id, eval_run_id=eval_run_id)
    ]
