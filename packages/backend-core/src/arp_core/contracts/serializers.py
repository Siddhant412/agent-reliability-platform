from __future__ import annotations

from uuid import UUID

from arp_core.contracts.approval import ApprovalRequestRead
from arp_core.contracts.audit import AuditEventRead
from arp_core.contracts.eval import DatasetRead, EvalCaseRead, EvalCaseResultRead, EvalRunRead
from arp_core.contracts.run import RunRead, ToolCallRead, TraceSpanRead
from arp_core.contracts.tenant import MembershipRead, OrganizationRead, ProjectRead
from arp_core.contracts.tooling import ConnectorRead, ToolDefinitionRead
from arp_core.contracts.workflow import (
    ModelConfig,
    WorkflowPolicyRule,
    WorkflowRead,
    WorkflowRolloutConfig,
    WorkflowToolRef,
    WorkflowVersionRead,
)
from arp_core.persistence.models import (
    ApprovalRequest,
    AuditEvent,
    Connector,
    Dataset,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    Membership,
    Organization,
    Project,
    Run,
    ToolDefinition,
    ToolCall,
    TraceSpan,
    Workflow,
    WorkflowVersion,
)


def organization_to_read(record: Organization) -> OrganizationRead:
    return OrganizationRead.model_validate(record)


def project_to_read(record: Project) -> ProjectRead:
    return ProjectRead.model_validate(record)


def membership_to_read(record: Membership) -> MembershipRead:
    return MembershipRead.model_validate(record)


def workflow_to_read(record: Workflow) -> WorkflowRead:
    return WorkflowRead.model_validate(record)


def workflow_version_to_read(record: WorkflowVersion) -> WorkflowVersionRead:
    return WorkflowVersionRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version=record.version,
        status=record.status,
        prompt_template=record.prompt_template,
        input_schema=record.input_schema_json,
        output_schema=record.output_schema_json,
        model_config_payload=ModelConfig.model_validate(record.model_config_json),
        policy_pack=[WorkflowPolicyRule.model_validate(item) for item in record.policy_pack_json],
        tool_set=[WorkflowToolRef.model_validate(item) for item in record.tool_set_json],
        guardrails=list(record.guardrails_json),
        rollout_config=(
            WorkflowRolloutConfig.model_validate(record.rollout_config_json)
            if record.rollout_config_json
            else None
        ),
        eval_dataset_bindings=[UUID(item) for item in record.eval_dataset_bindings_json],
        created_by=record.created_by,
        created_at=record.created_at,
        published_at=record.published_at,
    )


def run_to_read(record: Run) -> RunRead:
    return RunRead(
        id=record.id,
        project_id=record.project_id,
        workflow_version_id=record.workflow_version_id,
        triggered_by=record.triggered_by,
        status=record.status,
        input_payload=record.input_json,
        final_output=record.final_output_json,
        started_at=record.started_at,
        ended_at=record.ended_at,
        latency_ms=record.latency_ms,
        cost_usd=record.cost_usd,
        tokens_input=record.tokens_input,
        tokens_output=record.tokens_output,
        feedback_score=record.feedback_score,
        created_at=record.created_at,
    )


def trace_span_to_read(record: TraceSpan) -> TraceSpanRead:
    return TraceSpanRead(
        id=record.id,
        project_id=record.project_id,
        workflow_version_id=record.workflow_version_id,
        run_id=record.run_id,
        trace_id=record.trace_id,
        span_id=record.span_id,
        parent_span_id=record.parent_span_id,
        span_type=record.span_type,
        name=record.name,
        status=record.status,
        started_at=record.started_at,
        ended_at=record.ended_at,
        attributes=record.attributes_json,
        error=record.error_json,
        created_at=record.created_at,
    )


def tool_call_to_read(record: ToolCall) -> ToolCallRead:
    return ToolCallRead(
        id=record.id,
        project_id=record.project_id,
        run_id=record.run_id,
        span_id=record.span_id,
        tool_name=record.tool_name,
        args=record.args_json,
        status=record.status,
        approval_required=record.approval_required,
        approval_id=record.approval_id,
        result=record.result_json,
        error=record.error_json,
        created_at=record.created_at,
    )


def approval_request_to_read(record: ApprovalRequest) -> ApprovalRequestRead:
    return ApprovalRequestRead(
        id=record.id,
        project_id=record.project_id,
        run_id=record.run_id,
        tool_call_id=record.tool_call_id,
        approver_role=record.approver_role,
        status=record.status,
        reason=record.reason,
        run_context=record.run_context_json,
        proposed_effect=record.proposed_effect_json,
        requested_at=record.requested_at,
        decided_at=record.decided_at,
        decided_by=record.decided_by,
        decision_note=record.decision_note,
    )


def audit_event_to_read(record: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=record.id,
        actor_user_id=record.actor_user_id,
        org_id=record.org_id,
        project_id=record.project_id,
        action=record.action,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        before=record.before_json,
        after=record.after_json,
        created_at=record.created_at,
    )


def connector_to_read(record: Connector) -> ConnectorRead:
    return ConnectorRead(
        id=record.id,
        org_id=record.org_id,
        project_id=record.project_id,
        name=record.name,
        connector_type=record.connector_type,
        auth_mode=record.auth_mode,
        scopes=record.scopes_json,
        status=record.status,
        owner_user_id=record.owner_user_id,
        created_at=record.created_at,
    )


def tool_definition_to_read(record: ToolDefinition) -> ToolDefinitionRead:
    return ToolDefinitionRead(
        id=record.id,
        connector_id=record.connector_id,
        name=record.name,
        description=record.description,
        risk_level=record.risk_level,
        input_schema=record.input_schema_json,
        output_schema=record.output_schema_json,
        is_mutating=record.is_mutating,
        created_at=record.created_at,
    )


def dataset_to_read(record: Dataset) -> DatasetRead:
    return DatasetRead(
        id=record.id,
        project_id=record.project_id,
        name=record.name,
        version=record.version,
        description=record.description,
        created_by=record.created_by,
        created_at=record.created_at,
    )


def eval_case_to_read(record: EvalCase) -> EvalCaseRead:
    return EvalCaseRead(
        id=record.id,
        dataset_id=record.dataset_id,
        input_payload=record.input_json,
        expected=record.expected_json,
        tags=record.tags_json,
        created_at=record.created_at,
    )


def eval_run_to_read(record: EvalRun) -> EvalRunRead:
    return EvalRunRead(
        id=record.id,
        dataset_id=record.dataset_id,
        workflow_version_id=record.workflow_version_id,
        baseline_version_id=record.baseline_version_id,
        status=record.status,
        summary=record.summary_json,
        started_at=record.started_at,
        ended_at=record.ended_at,
        created_at=record.created_at,
    )


def eval_case_result_to_read(record: EvalCaseResult) -> EvalCaseResultRead:
    return EvalCaseResultRead(
        id=record.id,
        eval_run_id=record.eval_run_id,
        eval_case_id=record.eval_case_id,
        run_id=record.run_id,
        status=record.status,
        scores=record.scores_json,
        output=record.output_json,
        trace_grade=record.trace_grade_json,
        error=record.error_json,
        created_at=record.created_at,
    )
