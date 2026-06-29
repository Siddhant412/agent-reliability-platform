from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arp_core.domain.enums import ApprovalStatus, MembershipRole


class ApprovalDecisionRequest(BaseModel):
    status: ApprovalStatus
    decision_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_decision_status(self) -> "ApprovalDecisionRequest":
        if self.status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("approval decision must be approved or rejected")
        return self


class ApprovalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    run_id: UUID
    tool_call_id: UUID
    approver_role: MembershipRole
    status: ApprovalStatus
    reason: str
    run_context: dict[str, Any] | None = None
    proposed_effect: dict[str, Any] | None = None
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    decision_note: str | None = None
