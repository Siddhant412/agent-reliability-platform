"""Initial platform schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_000001"
down_revision = None
branch_labels = None
depends_on = None


membership_role_enum = sa.Enum(
    "platform_admin",
    "org_admin",
    "project_admin",
    "ai_engineer",
    "supervisor",
    "team_lead",
    "operator",
    "analyst",
    "api_client",
    name="membershiprole",
    native_enum=False,
)
connector_type_enum = sa.Enum("mcp", "local", name="connectortype", native_enum=False)
connector_auth_mode_enum = sa.Enum(
    "none",
    "api_key",
    "oauth",
    "service_account",
    name="connectorauthmode",
    native_enum=False,
)
connector_status_enum = sa.Enum("active", "degraded", "disabled", "unknown", name="connectorstatus", native_enum=False)
tool_risk_level_enum = sa.Enum("low", "medium", "high", name="toolrisklevel", native_enum=False)
workflow_version_status_enum = sa.Enum("draft", "published", "archived", name="workflowversionstatus", native_enum=False)
run_status_enum = sa.Enum(
    "queued",
    "running",
    "awaiting_approval",
    "resumed",
    "succeeded",
    "failed",
    "cancelled",
    name="runstatus",
    native_enum=False,
)
span_status_enum = sa.Enum("ok", "error", "cancelled", "in_progress", name="spanstatus", native_enum=False)
tool_call_status_enum = sa.Enum(
    "proposed",
    "blocked",
    "approved",
    "executed",
    "rejected",
    "failed",
    name="toolcallstatus",
    native_enum=False,
)
approval_status_enum = sa.Enum("pending", "approved", "rejected", "cancelled", name="approvalstatus", native_enum=False)
project_environment_enum = sa.Enum("dev", "staging", "prod", name="projectenvironment", native_enum=False)
eval_run_status_enum = sa.Enum("queued", "running", "succeeded", "failed", name="evalrunstatus", native_enum=False)
eval_case_status_enum = sa.Enum("pending", "succeeded", "failed", name="evalcasestatus", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_table(
        "projects",
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("environment", project_environment_enum, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_projects_org_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("org_id", "slug", name="uq_projects_org_slug"),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("role", membership_role_enum, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("org_id IS NOT NULL", name="ck_memberships_memberships_org_required"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_memberships_org_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_memberships_project_id_projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("user_id", "org_id", "project_id", name="uq_memberships_user_scope"),
    )
    op.create_table(
        "connectors",
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connector_type", connector_type_enum, nullable=False),
        sa.Column("auth_mode", connector_auth_mode_enum, nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("status", connector_status_enum, nullable=False),
        sa.Column("owner_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("org_id IS NOT NULL OR project_id IS NOT NULL", name="ck_connectors_connectors_scope_required"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_connectors_org_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_connectors_project_id_projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_connectors"),
    )
    op.create_table(
        "tool_definitions",
        sa.Column("connector_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk_level", tool_risk_level_enum, nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("output_schema_json", sa.JSON(), nullable=False),
        sa.Column("is_mutating", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], name="fk_tool_definitions_connector_id_connectors", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_tool_definitions"),
        sa.UniqueConstraint("connector_id", "name", name="uq_tool_definitions_connector_name"),
    )
    op.create_table(
        "workflows",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_workflows_project_id_projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workflows"),
        sa.UniqueConstraint("project_id", "slug", name="uq_workflows_project_slug"),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", workflow_version_status_enum, nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("output_schema_json", sa.JSON(), nullable=False),
        sa.Column("model_config_json", sa.JSON(), nullable=False),
        sa.Column("policy_pack_json", sa.JSON(), nullable=False),
        sa.Column("tool_set_json", sa.JSON(), nullable=False),
        sa.Column("guardrails_json", sa.JSON(), nullable=False),
        sa.Column("rollout_config_json", sa.JSON(), nullable=True),
        sa.Column("eval_dataset_bindings_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], name="fk_workflow_versions_workflow_id_workflows", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_versions"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )
    op.create_table(
        "runs",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("triggered_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", run_status_enum, nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("final_output_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("feedback_score", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_runs_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"], name="fk_runs_workflow_version_id_workflow_versions", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_index("ix_runs_project_status", "runs", ["project_id", "status"], unique=False)
    op.create_index("ix_runs_project_workflow_version", "runs", ["project_id", "workflow_version_id"], unique=False)
    op.create_table(
        "trace_spans",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("parent_span_id", sa.String(length=16), nullable=True),
        sa.Column("span_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", span_status_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_trace_spans_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_trace_spans_run_id_runs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"], name="fk_trace_spans_workflow_version_id_workflow_versions", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_trace_spans"),
        sa.UniqueConstraint("project_id", "run_id", "trace_id", "span_id", name="uq_trace_spans_trace_span"),
    )
    op.create_index("ix_trace_spans_run_started_at", "trace_spans", ["run_id", "started_at"], unique=False)
    op.create_table(
        "tool_calls",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("status", tool_call_status_enum, nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approval_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tool_calls_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_tool_calls_run_id_runs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
    )
    op.create_index("ix_tool_calls_project_status", "tool_calls", ["project_id", "status"], unique=False)
    op.create_index("ix_tool_calls_run_status", "tool_calls", ["run_id", "status"], unique=False)
    op.create_table(
        "approval_requests",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("approver_role", membership_role_enum, nullable=False),
        sa.Column("status", approval_status_enum, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("run_context_json", sa.JSON(), nullable=True),
        sa.Column("proposed_effect_json", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_approval_requests_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_approval_requests_run_id_runs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"], name="fk_approval_requests_tool_call_id_tool_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_approval_requests"),
        sa.UniqueConstraint("tool_call_id", name="uq_approval_requests_tool_call_id"),
    )
    op.create_index("ix_approval_requests_project_status", "approval_requests", ["project_id", "status"], unique=False)
    op.create_table(
        "datasets",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_datasets_project_id_projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.UniqueConstraint("project_id", "name", "version", name="uq_datasets_project_name_version"),
    )
    op.create_table(
        "eval_cases",
        sa.Column("dataset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("expected_json", sa.JSON(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], name="fk_eval_cases_dataset_id_datasets", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_eval_cases"),
    )
    op.create_index("ix_eval_cases_dataset", "eval_cases", ["dataset_id"], unique=False)
    op.create_table(
        "eval_runs",
        sa.Column("dataset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("baseline_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", eval_run_status_enum, nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["baseline_version_id"], ["workflow_versions.id"], name="fk_eval_runs_baseline_version_id_workflow_versions", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], name="fk_eval_runs_dataset_id_datasets", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"], name="fk_eval_runs_workflow_version_id_workflow_versions", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_eval_runs"),
    )
    op.create_index("ix_eval_runs_dataset_status", "eval_runs", ["dataset_id", "status"], unique=False)
    op.create_table(
        "eval_case_results",
        sa.Column("eval_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("eval_case_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", eval_case_status_enum, nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("trace_grade_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["eval_case_id"], ["eval_cases.id"], name="fk_eval_case_results_eval_case_id_eval_cases", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], name="fk_eval_case_results_eval_run_id_eval_runs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_eval_case_results_run_id_runs", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_eval_case_results"),
        sa.UniqueConstraint("eval_run_id", "eval_case_id", name="uq_eval_case_results_eval_run_case"),
    )
    op.create_index("ix_eval_case_results_eval_run_status", "eval_case_results", ["eval_run_id", "status"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_audit_events_org_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_audit_events_project_id_projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_org_project_created", "audit_events", ["org_id", "project_id", "created_at"], unique=False)
    op.create_index("ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_org_project_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_eval_case_results_eval_run_status", table_name="eval_case_results")
    op.drop_table("eval_case_results")
    op.drop_index("ix_eval_runs_dataset_status", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_dataset", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_table("datasets")
    op.drop_index("ix_approval_requests_project_status", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_tool_calls_run_status", table_name="tool_calls")
    op.drop_index("ix_tool_calls_project_status", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_trace_spans_run_started_at", table_name="trace_spans")
    op.drop_table("trace_spans")
    op.drop_index("ix_runs_project_workflow_version", table_name="runs")
    op.drop_index("ix_runs_project_status", table_name="runs")
    op.drop_table("runs")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
    op.drop_table("tool_definitions")
    op.drop_table("connectors")
    op.drop_table("memberships")
    op.drop_table("projects")
    op.drop_table("organizations")
