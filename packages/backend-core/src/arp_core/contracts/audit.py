from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None = None
    org_id: UUID | None = None
    project_id: UUID | None = None
    action: str
    resource_type: str
    resource_id: UUID | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime
