from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import get_authenticated_actor, require_project_access
from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz
from arp_core.application import services
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.run import (
    RunRead,
    RunSubmitRequest,
    RunTimelineRead,
    RunTransitionRequest,
    ToolCallRead,
    TraceSpanCreate,
    TraceSpanRead,
    WorkflowRunSubmitRequest,
)
from arp_core.contracts.serializers import approval_request_to_read, run_to_read, tool_call_to_read, trace_span_to_read
from arp_core.domain.enums import SpanStatus
from arp_worker.runner import execute_run as execute_worker_run


router = APIRouter(tags=["runs"])


@router.get("/api/v1/projects/{project_id}/runs", response_model=list[RunRead])
def list_runs(
    project_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[RunRead]:
    return [run_to_read(record) for record in services.list_runs(session, project_id=project_id)]


@router.post("/api/v1/projects/{project_id}/runs", response_model=RunRead, status_code=status.HTTP_201_CREATED)
def submit_run(
    project_id: UUID,
    payload: RunSubmitRequest,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
) -> RunRead:
    run = services.submit_run(session, project_id=project_id, payload=payload, actor_user_id=actor.user_id)
    return run_to_read(run)


@router.post(
    "/api/v1/projects/{project_id}/workflows/{workflow_slug}/runs",
    response_model=RunRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_workflow_run(
    project_id: UUID,
    workflow_slug: str,
    payload: WorkflowRunSubmitRequest,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
) -> RunRead:
    run = services.submit_workflow_run(
        session,
        project_id=project_id,
        workflow_slug=workflow_slug,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return run_to_read(run)


@router.patch("/api/v1/projects/{project_id}/runs/{run_id}/status", response_model=RunRead)
def transition_run_status(
    project_id: UUID,
    run_id: UUID,
    payload: RunTransitionRequest,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_write_workflows))],
    session: Annotated[Session, Depends(get_db_session)],
) -> RunRead:
    run = services.transition_run_status(session, project_id=project_id, run_id=run_id, payload=payload)
    return run_to_read(run)


@router.post("/api/v1/projects/{project_id}/runs/{run_id}/execute", response_model=RunRead)
def execute_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_write_workflows))],
    session: Annotated[Session, Depends(get_db_session)],
) -> RunRead:
    if request.app.state.settings.auth_mode != "development_header":
        raise authz.AuthorizationError("inline execution is disabled outside development_header mode")
    execute_worker_run(session, project_id=project_id, run_id=run_id)
    run = services.get_run(session, project_id=project_id, run_id=run_id)
    return run_to_read(run)


@router.post("/api/v1/projects/{project_id}/runs/{run_id}/enqueue", response_model=RunRead)
def enqueue_run(
    project_id: UUID,
    run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
) -> RunRead:
    run = services.enqueue_run(session, project_id=project_id, run_id=run_id, actor_user_id=actor.user_id)
    return run_to_read(run)


@router.get("/api/v1/projects/{project_id}/runs/{run_id}/trace-spans", response_model=list[TraceSpanRead])
def list_trace_spans(
    project_id: UUID,
    run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
    span_type: str | None = Query(default=None),
    status: SpanStatus | None = Query(default=None),
) -> list[TraceSpanRead]:
    return [
        trace_span_to_read(record)
        for record in services.list_trace_spans(
            session,
            project_id=project_id,
            run_id=run_id,
            span_type=span_type,
            status=status,
        )
    ]


@router.get("/api/v1/projects/{project_id}/runs/{run_id}/timeline", response_model=RunTimelineRead)
def get_run_timeline(
    project_id: UUID,
    run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
) -> RunTimelineRead:
    run = services.get_run(session, project_id=project_id, run_id=run_id)
    return RunTimelineRead(
        run=run_to_read(run),
        trace_spans=[
            trace_span_to_read(record)
            for record in services.list_trace_spans(session, project_id=project_id, run_id=run_id)
        ],
        tool_calls=[
            tool_call_to_read(record)
            for record in services.list_tool_calls(session, project_id=project_id, run_id=run_id)
        ],
        approvals=[
            approval_request_to_read(record)
            for record in services.list_approval_requests(session, project_id=project_id, run_id=run_id)
        ],
    )


@router.post(
    "/api/v1/projects/{project_id}/runs/{run_id}/trace-spans",
    response_model=TraceSpanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_trace_span(
    project_id: UUID,
    run_id: UUID,
    payload: TraceSpanCreate,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_write_workflows))],
    session: Annotated[Session, Depends(get_db_session)],
) -> TraceSpanRead:
    span = services.create_trace_span(session, project_id=project_id, run_id=run_id, payload=payload)
    return trace_span_to_read(span)


@router.get("/api/v1/projects/{project_id}/runs/{run_id}/tool-calls", response_model=list[ToolCallRead])
def list_tool_calls(
    project_id: UUID,
    run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ToolCallRead]:
    return [
        tool_call_to_read(record)
        for record in services.list_tool_calls(session, project_id=project_id, run_id=run_id)
    ]


@router.get("/api/v1/projects/{project_id}/runs/{run_id}", response_model=RunRead)
def get_run(
    project_id: UUID,
    run_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
) -> RunRead:
    run = services.get_run(session, project_id=project_id, run_id=run_id)
    return run_to_read(run)
