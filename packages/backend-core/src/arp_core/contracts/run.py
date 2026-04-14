from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from arp_core.domain.enums import RunStatus


class RunSubmitRequest(BaseModel):
    workflow_version_id: UUID
    input_payload: dict[str, Any]
    triggered_by: UUID | None = None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_version_id: UUID
    triggered_by: UUID | None = None
    status: RunStatus
    input_payload: dict[str, Any]
    final_output: dict[str, Any] | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    latency_ms: int | None = None
    cost_usd: Decimal | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    feedback_score: Decimal | None = None
    created_at: datetime

