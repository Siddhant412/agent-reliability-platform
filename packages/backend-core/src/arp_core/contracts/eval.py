from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from arp_core.domain.enums import EvalCaseStatus, EvalRunStatus


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=64)
    description: str | None = None


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    version: str
    description: str | None = None
    created_by: UUID | None = None
    created_at: datetime


class EvalCaseCreate(BaseModel):
    input_payload: dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class EvalCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    input_payload: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str]
    created_at: datetime


class EvalRunCreate(BaseModel):
    dataset_id: UUID
    workflow_version_id: UUID
    baseline_version_id: UUID | None = None


class EvalRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    workflow_version_id: UUID
    baseline_version_id: UUID | None = None
    status: EvalRunStatus
    summary: dict[str, Any]
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime


class EvalCaseResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    eval_run_id: UUID
    eval_case_id: UUID
    run_id: UUID | None = None
    status: EvalCaseStatus
    scores: dict[str, Any]
    output: dict[str, Any] | None = None
    trace_grade: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
