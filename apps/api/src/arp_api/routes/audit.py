from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import require_project_access
from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz
from arp_core.application import services
from arp_core.contracts.audit import AuditEventRead
from arp_core.contracts.serializers import audit_event_to_read


router = APIRouter(tags=["audit"])


@router.get("/api/v1/projects/{project_id}/audit-events", response_model=list[AuditEventRead])
def list_audit_events(
    project_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
    action: str | None = Query(default=None, min_length=1, max_length=160),
    resource_type: str | None = Query(default=None, min_length=1, max_length=120),
    resource_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditEventRead]:
    return [
        audit_event_to_read(record)
        for record in services.list_audit_events(
            session,
            project_id=project_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            limit=limit,
        )
    ]
