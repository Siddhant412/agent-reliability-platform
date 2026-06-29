from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import get_authenticated_actor, require_project_access
from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz
from arp_core.application import services
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.approval import ApprovalDecisionRequest, ApprovalRequestRead
from arp_core.contracts.serializers import approval_request_to_read
from arp_core.domain.enums import ApprovalStatus


router = APIRouter(tags=["approvals"])


@router.get("/api/v1/projects/{project_id}/approvals", response_model=list[ApprovalRequestRead])
def list_approvals(
    project_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
    status: ApprovalStatus | None = Query(default=None),
) -> list[ApprovalRequestRead]:
    return [
        approval_request_to_read(record)
        for record in services.list_approval_requests(session, project_id=project_id, status=status)
    ]


@router.get("/api/v1/projects/{project_id}/approvals/{approval_id}", response_model=ApprovalRequestRead)
def get_approval(
    project_id: UUID,
    approval_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    session: Annotated[Session, Depends(get_db_session)],
) -> ApprovalRequestRead:
    approval = services.get_approval_request(session, project_id=project_id, approval_id=approval_id)
    return approval_request_to_read(approval)


@router.post("/api/v1/projects/{project_id}/approvals/{approval_id}/decide", response_model=ApprovalRequestRead)
def decide_approval(
    project_id: UUID,
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    access: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_access_runs))],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ApprovalRequestRead:
    approval = services.get_approval_request(session, project_id=project_id, approval_id=approval_id)
    authz.ensure_project_can_decide_approval(access, approver_role=approval.approver_role)
    approval = services.decide_approval_request(
        session,
        project_id=project_id,
        approval_id=approval_id,
        status=payload.status,
        decided_by=actor.user_id,
        decision_note=payload.decision_note,
    )
    return approval_request_to_read(approval)
