from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from arp_core.persistence.models import AuditEvent


def record_audit_event(
    session: Session,
    *,
    actor_user_id: UUID | None,
    org_id: UUID | None,
    project_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    before_json: dict[str, Any] | None,
    after_json: dict[str, Any] | None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        org_id=org_id,
        project_id=project_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_json=before_json,
        after_json=after_json,
    )
    session.add(event)
    return event

