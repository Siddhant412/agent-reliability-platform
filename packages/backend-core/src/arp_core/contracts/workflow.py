from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arp_core.domain.enums import MembershipRole, PolicyAction, RolloutStrategy, WorkflowVersionStatus


class ModelConfig(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    temperature: float = Field(ge=0, le=2, default=0)
    max_output_tokens: int | None = Field(default=None, ge=1)


class WorkflowToolRef(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def normalize_string_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    name: str = Field(min_length=1, max_length=120)
    connector_id: UUID | None = None


class WorkflowPolicyRule(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    when: str = Field(min_length=1)
    action: PolicyAction
    approver_role: MembershipRole | None = None

    @model_validator(mode="after")
    def validate_approver_role(self) -> "WorkflowPolicyRule":
        if self.action == PolicyAction.REQUIRE_APPROVAL and self.approver_role is None:
            raise ValueError("approver_role is required when action is require_approval")
        if self.action != PolicyAction.REQUIRE_APPROVAL and self.approver_role is not None:
            raise ValueError("approver_role is only valid for require_approval policies")
        return self


class RolloutTrafficSplit(BaseModel):
    baseline: int = Field(ge=0, le=100)
    candidate: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_percentages(self) -> "RolloutTrafficSplit":
        if self.baseline + self.candidate != 100:
            raise ValueError("baseline and candidate traffic split must add up to 100")
        return self


class RollbackThresholds(BaseModel):
    policy_violation_rate: float | None = Field(default=None, ge=0)
    schema_failure_rate: float | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=1)


class WorkflowRolloutConfig(BaseModel):
    strategy: RolloutStrategy = RolloutStrategy.DIRECT
    baseline_version: str | None = None
    candidate_version: str | None = None
    traffic_split: RolloutTrafficSplit | None = None
    rollback_thresholds: RollbackThresholds | None = None

    @model_validator(mode="after")
    def validate_strategy(self) -> "WorkflowRolloutConfig":
        if self.strategy == RolloutStrategy.CANARY and self.traffic_split is None:
            raise ValueError("traffic_split is required for canary rollouts")
        return self


class WorkflowCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=120)
    description: str | None = None


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    slug: str
    name: str
    domain: str
    description: str | None = None
    created_at: datetime


class WorkflowVersionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str = Field(min_length=1, max_length=64)
    prompt_template: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    model_config_payload: ModelConfig = Field(validation_alias="model_config", serialization_alias="model_config")
    policy_pack: list[WorkflowPolicyRule] = Field(default_factory=list)
    tool_set: list[WorkflowToolRef] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    rollout_config: WorkflowRolloutConfig | None = None
    eval_dataset_bindings: list[UUID] = Field(default_factory=list)
    created_by: UUID | None = None


class WorkflowVersionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str | None = Field(default=None, min_length=1, max_length=64)
    prompt_template: str | None = Field(default=None, min_length=1)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    model_config_payload: ModelConfig | None = Field(
        default=None,
        validation_alias="model_config",
        serialization_alias="model_config",
    )
    policy_pack: list[WorkflowPolicyRule] | None = None
    tool_set: list[WorkflowToolRef] | None = None
    guardrails: list[str] | None = None
    rollout_config: WorkflowRolloutConfig | None = None
    eval_dataset_bindings: list[UUID] | None = None


class WorkflowVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workflow_id: UUID
    version: str
    status: WorkflowVersionStatus
    prompt_template: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    model_config_payload: ModelConfig = Field(serialization_alias="model_config")
    policy_pack: list[WorkflowPolicyRule]
    tool_set: list[WorkflowToolRef]
    guardrails: list[str]
    rollout_config: WorkflowRolloutConfig | None = None
    eval_dataset_bindings: list[UUID]
    created_by: UUID | None = None
    created_at: datetime
    published_at: datetime | None = None


class PublishWorkflowVersionRequest(BaseModel):
    published_by: UUID | None = None
