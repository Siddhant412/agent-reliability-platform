from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


JSONValue = dict[str, Any]
JSONArrayValue = list[dict[str, Any] | str | int | float | bool | None]


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuditStamp(BaseModel):
    created_at: datetime


class CostSummary(BaseModel):
    cost_usd: Decimal | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None


class ActorHeader(BaseModel):
    actor_user_id: UUID | None = None

