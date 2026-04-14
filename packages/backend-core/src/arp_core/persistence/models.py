from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arp_core.domain.enums import (
    ApprovalStatus,
    ConnectorAuthMode,
    ConnectorStatus,
    ConnectorType,
    EvalCaseStatus,
    EvalRunStatus,
    MembershipRole,
    ProjectEnvironment,
    RunStatus,
    SpanStatus,
    ToolCallStatus,
    ToolRiskLevel,
    WorkflowVersionStatus,
)
from arp_core.persistence.base import Base, CreatedAtMixin, JSON_TYPE, UUIDPrimaryKeyMixin, UUID_TYPE, utcnow


def enum_column(enum_cls: type) -> Enum:
    return Enum(enum_cls, native_enum=False, values_callable=lambda items: [item.value for item in items])


class Organization(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class Project(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_projects_org_slug"),)

    org_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    environment: Mapped[ProjectEnvironment] = mapped_column(
        enum_column(ProjectEnvironment),
        nullable=False,
        default=ProjectEnvironment.DEV,
    )

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="project")


class Membership(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", "project_id", name="uq_memberships_user_scope"),
        CheckConstraint("org_id IS NOT NULL", name="memberships_org_required"),
    )

    user_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    org_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    role: Mapped[MembershipRole] = mapped_column(enum_column(MembershipRole), nullable=False)


class Connector(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (
        CheckConstraint(
            "org_id IS NOT NULL OR project_id IS NOT NULL",
            name="connectors_scope_required",
        ),
    )

    org_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_type: Mapped[ConnectorType] = mapped_column(enum_column(ConnectorType), nullable=False)
    auth_mode: Mapped[ConnectorAuthMode] = mapped_column(enum_column(ConnectorAuthMode), nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    status: Mapped[ConnectorStatus] = mapped_column(
        enum_column(ConnectorStatus),
        nullable=False,
        default=ConnectorStatus.UNKNOWN,
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)

    tools: Mapped[list["ToolDefinition"]] = relationship(back_populates="connector")


class ToolDefinition(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_definitions"
    __table_args__ = (UniqueConstraint("connector_id", "name", name="uq_tool_definitions_connector_name"),)

    connector_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[ToolRiskLevel] = mapped_column(enum_column(ToolRiskLevel), nullable=False)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    is_mutating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    connector: Mapped["Connector"] = relationship(back_populates="tools")


class Workflow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_workflows_project_slug"),)

    project_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="workflows")
    versions: Mapped[list["WorkflowVersion"]] = relationship(back_populates="workflow")


class WorkflowVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),)

    workflow_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[WorkflowVersionStatus] = mapped_column(
        enum_column(WorkflowVersionStatus),
        nullable=False,
        default=WorkflowVersionStatus.DRAFT,
    )
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    model_config_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    policy_pack_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    tool_set_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    guardrails_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    rollout_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    eval_dataset_bindings_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    created_by: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped["Workflow"] = relationship(back_populates="versions")
    runs: Mapped[list["Run"]] = relationship(back_populates="workflow_version")


class Run(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_project_status", "project_id", "status"),
        Index("ix_runs_project_workflow_version", "project_id", "workflow_version_id"),
    )

    project_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    triggered_by: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    status: Mapped[RunStatus] = mapped_column(enum_column(RunStatus), nullable=False, default=RunStatus.QUEUED)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    final_output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)

    workflow_version: Mapped["WorkflowVersion"] = relationship(back_populates="runs")
    trace_spans: Mapped[list["TraceSpan"]] = relationship(back_populates="run")
    tool_calls: Mapped[list["ToolCall"]] = relationship(back_populates="run")


class TraceSpan(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "trace_spans"
    __table_args__ = (
        UniqueConstraint("project_id", "run_id", "trace_id", "span_id", name="uq_trace_spans_trace_span"),
        Index("ix_trace_spans_run_started_at", "run_id", "started_at"),
    )

    project_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    span_id: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    span_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SpanStatus] = mapped_column(enum_column(SpanStatus), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="trace_spans")


class ToolCall(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_run_status", "run_id", "status"),
        Index("ix_tool_calls_project_status", "project_id", "status"),
    )

    project_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    args_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[ToolCallStatus] = mapped_column(enum_column(ToolCallStatus), nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="tool_calls")
    approval_request: Mapped["ApprovalRequest | None"] = relationship(back_populates="tool_call")


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approval_requests_project_status", "project_id", "status"),)

    project_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    tool_call_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("tool_calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    approver_role: Mapped[MembershipRole] = mapped_column(enum_column(MembershipRole), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    run_context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    proposed_effect_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    tool_call: Mapped["ToolCall"] = relationship(back_populates="approval_request")


class Dataset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("project_id", "name", "version", name="uq_datasets_project_name_version"),)

    project_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)

    eval_cases: Mapped[list["EvalCase"]] = relationship(back_populates="dataset")


class EvalCase(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "eval_cases"
    __table_args__ = (Index("ix_eval_cases_dataset", "dataset_id"),)

    dataset_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    expected_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)

    dataset: Mapped["Dataset"] = relationship(back_populates="eval_cases")


class EvalRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_dataset_status", "dataset_id", "status"),)

    dataset_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    workflow_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    baseline_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[EvalRunStatus] = mapped_column(
        enum_column(EvalRunStatus),
        nullable=False,
        default=EvalRunStatus.QUEUED,
    )
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalCaseResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "eval_case_results"
    __table_args__ = (
        UniqueConstraint("eval_run_id", "eval_case_id", name="uq_eval_case_results_eval_run_case"),
        Index("ix_eval_case_results_eval_run_status", "eval_run_id", "status"),
    )

    eval_run_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False)
    eval_case_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[EvalCaseStatus] = mapped_column(enum_column(EvalCaseStatus), nullable=False)
    scores_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    trace_grade_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)


class AuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_project_created", "org_id", "project_id", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    org_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
