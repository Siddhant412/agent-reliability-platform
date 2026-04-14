from __future__ import annotations

from uuid import UUID

from arp_core.contracts.run import RunRead
from arp_core.contracts.tenant import MembershipRead, OrganizationRead, ProjectRead
from arp_core.contracts.workflow import (
    ModelConfig,
    WorkflowPolicyRule,
    WorkflowRead,
    WorkflowRolloutConfig,
    WorkflowToolRef,
    WorkflowVersionRead,
)
from arp_core.persistence.models import Membership, Organization, Project, Run, Workflow, WorkflowVersion


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
