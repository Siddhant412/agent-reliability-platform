from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from arp_core.domain.enums import RunStatus, SpanStatus, ToolCallStatus


class RunSubmitRequest(BaseModel):
    workflow_version_id: UUID
    input_payload: dict[str, Any]
    triggered_by: UUID | None = None


class WorkflowRunSubmitRequest(BaseModel):
    input_payload: dict[str, Any]
    triggered_by: UUID | None = None


class RunTransitionRequest(BaseModel):
    status: RunStatus
    final_output: dict[str, Any] | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    cost_usd: Decimal | None = Field(default=None, ge=0)
    tokens_input: int | None = Field(default=None, ge=0)
    tokens_output: int | None = Field(default=None, ge=0)


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


class TraceSpanCreate(BaseModel):
    trace_id: str = Field(min_length=1, max_length=32)
    span_id: str = Field(min_length=1, max_length=16)
    parent_span_id: str | None = Field(default=None, min_length=1, max_length=16)
    span_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    status: SpanStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class TraceSpanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_version_id: UUID | None = None
    run_id: UUID
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    span_type: str
    name: str
    status: SpanStatus
    started_at: datetime
    ended_at: datetime | None = None
    attributes: dict[str, Any]
    error: dict[str, Any] | None = None
    created_at: datetime


class ToolCallCreate(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    args: dict[str, Any]
    span_id: str | None = Field(default=None, min_length=1, max_length=16)
    approval_required: bool = False


class ToolCallUpdate(BaseModel):
    status: ToolCallStatus
    span_id: str | None = Field(default=None, min_length=1, max_length=16)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    run_id: UUID
    span_id: str | None = None
    tool_name: str
    args: dict[str, Any]
    status: ToolCallStatus
    approval_required: bool
    approval_id: UUID | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
