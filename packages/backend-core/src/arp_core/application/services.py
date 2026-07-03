from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JSONSchemaValidationError
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from arp_core.application.audit import record_audit_event
from arp_core.application.exceptions import ApplicationError, ConflictError, NotFoundError
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.eval import DatasetCreate, EvalCaseCreate, EvalRunCreate
from arp_core.contracts.run import (
    RunSubmitRequest,
    RunTransitionRequest,
    ToolCallCreate,
    ToolCallUpdate,
    TraceSpanCreate,
    WorkflowRunSubmitRequest,
)
from arp_core.contracts.tenant import MembershipCreate, OrganizationCreate, ProjectCreate
from arp_core.contracts.tooling import ConnectorCreate, ToolDefinitionCreate
from arp_core.contracts.workflow import (
    ActivateWorkflowRolloutRequest,
    PublishWorkflowVersionRequest,
    RolloutMonitorRead,
    SetActiveWorkflowVersionRequest,
    WorkflowCreate,
    WorkflowVersionCreate,
    WorkflowVersionUpdate,
)
from arp_core.domain.enums import (
    ApprovalStatus,
    EvalCaseStatus,
    EvalRunStatus,
    MembershipRole,
    RolloutStrategy,
    RunStatus,
    SpanStatus,
    ToolCallStatus,
    WorkflowVersionStatus,
)
from arp_core.persistence.base import utcnow
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
from arp_core.workflow_registry.validation import build_workflow_definition_document, validate_workflow_definition


def _first_or_404(session: Session, statement: Select, message: str):
    result = session.scalar(statement)
    if result is None:
        raise NotFoundError(message)
    return result


def _workflow_version_snapshot(record: WorkflowVersion) -> dict[str, object]:
    return {
        "version": record.version,
        "status": record.status.value,
        "tool_count": len(record.tool_set_json),
        "policy_count": len(record.policy_pack_json),
        "guardrail_count": len(record.guardrails_json),
    }


def _json_schema_error_location(exc: JSONSchemaValidationError) -> str:
    location = "input_payload"
    for path_part in exc.absolute_path:
        if isinstance(path_part, int):
            location += f"[{path_part}]"
        else:
            location += f".{path_part}"
    return location


def _validate_run_input_payload(*, input_schema: dict, input_payload: dict) -> None:
    try:
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator(input_schema).validate(input_payload)
    except SchemaError as exc:
        raise ApplicationError(f"workflow input_schema is invalid: {exc.message}") from exc
    except JSONSchemaValidationError as exc:
        location = _json_schema_error_location(exc)
        raise ApplicationError(f"{location}: {exc.message}") from exc


TERMINAL_RUN_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
ACTIVE_RUN_STATUSES = {RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL, RunStatus.RESUMED}
ALLOWED_RUN_STATUS_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.AWAITING_APPROVAL,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.AWAITING_APPROVAL: {RunStatus.RESUMED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RESUMED: {RunStatus.RUNNING, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}
TERMINAL_TOOL_CALL_STATUSES = {
    ToolCallStatus.BLOCKED,
    ToolCallStatus.EXECUTED,
    ToolCallStatus.REJECTED,
    ToolCallStatus.FAILED,
}
ALLOWED_TOOL_CALL_STATUS_TRANSITIONS = {
    ToolCallStatus.PROPOSED: {
        ToolCallStatus.APPROVED,
        ToolCallStatus.BLOCKED,
        ToolCallStatus.EXECUTED,
        ToolCallStatus.REJECTED,
        ToolCallStatus.FAILED,
    },
    ToolCallStatus.APPROVED: {ToolCallStatus.EXECUTED, ToolCallStatus.FAILED, ToolCallStatus.REJECTED},
    ToolCallStatus.BLOCKED: set(),
    ToolCallStatus.EXECUTED: set(),
    ToolCallStatus.REJECTED: set(),
    ToolCallStatus.FAILED: set(),
}


def _ensure_run_transition_allowed(*, current_status: RunStatus, next_status: RunStatus) -> None:
    if current_status == next_status:
        return
    if next_status not in ALLOWED_RUN_STATUS_TRANSITIONS[current_status]:
        raise ConflictError(f"invalid run status transition: {current_status.value} -> {next_status.value}")


def _ensure_tool_call_transition_allowed(*, current_status: ToolCallStatus, next_status: ToolCallStatus) -> None:
    if current_status == next_status:
        return
    if next_status not in ALLOWED_TOOL_CALL_STATUS_TRANSITIONS[current_status]:
        raise ConflictError(f"invalid tool call status transition: {current_status.value} -> {next_status.value}")


def _latency_ms_between(started_at: datetime, ended_at: datetime) -> int:
    if started_at.tzinfo is None and ended_at.tzinfo is not None:
        ended_at = ended_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and ended_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _create_run_for_version(
    session: Session,
    *,
    project_id: UUID,
    version: WorkflowVersion,
    input_payload: dict,
    triggered_by: UUID | None,
    actor_user_id: UUID | None,
    routing_context: dict[str, object] | None = None,
) -> Run:
    _validate_run_input_payload(input_schema=version.input_schema_json, input_payload=input_payload)

    run = Run(
        project_id=project_id,
        workflow_version_id=version.id,
        triggered_by=triggered_by,
        status=RunStatus.QUEUED,
        input_json=input_payload,
        started_at=None,
        ended_at=None,
    )
    session.add(run)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id or triggered_by,
        org_id=version.workflow.project.org_id,
        project_id=project_id,
        action="run.submit",
        resource_type="run",
        resource_id=run.id,
        before_json=None,
        after_json={
            "workflow_version_id": str(version.id),
            "status": run.status.value,
            **({"routing": routing_context} if routing_context is not None else {}),
        },
    )
    return run


def _rollout_identity_key(*, input_payload: dict) -> str:
    for key in ("request_id", "ticket_id", "customer_id"):
        value = input_payload.get(key)
        if value is not None:
            return str(value)
    return json.dumps(input_payload, sort_keys=True, separators=(",", ":"))


def _rollout_bucket(*, project_id: UUID, workflow_slug: str, input_payload: dict) -> int:
    identity_key = _rollout_identity_key(input_payload=input_payload)
    digest = hashlib.sha256(f"{project_id}:{workflow_slug}:{identity_key}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _get_published_workflow_version_by_version(
    session: Session,
    *,
    workflow_id: UUID,
    version: str,
) -> WorkflowVersion | None:
    return session.scalar(
        select(WorkflowVersion)
        .options(joinedload(WorkflowVersion.workflow).joinedload(Workflow.project))
        .where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version == version,
            WorkflowVersion.status == WorkflowVersionStatus.PUBLISHED,
        )
    )


def _resolve_active_rollout_version(
    session: Session,
    *,
    workflow: Workflow,
    active_version: WorkflowVersion,
    input_payload: dict,
) -> tuple[WorkflowVersion, dict[str, object] | None]:
    config = active_version.rollout_config_json
    if not config or config.get("strategy") != RolloutStrategy.CANARY.value:
        return active_version, None
    if config.get("candidate_version") != active_version.version:
        return active_version, None

    traffic_split = config.get("traffic_split") or {}
    candidate_percentage = int(traffic_split.get("candidate") or 0)
    baseline_version = config.get("baseline_version")
    if not baseline_version:
        raise ConflictError("active rollout is missing baseline_version")

    baseline = _get_published_workflow_version_by_version(
        session,
        workflow_id=workflow.id,
        version=str(baseline_version),
    )
    if baseline is None:
        raise ConflictError("active rollout baseline version is not published")

    bucket = _rollout_bucket(project_id=workflow.project_id, workflow_slug=workflow.slug, input_payload=input_payload)
    selected_arm = "candidate" if bucket < candidate_percentage else "baseline"
    selected = active_version if selected_arm == "candidate" else baseline
    return selected, {
        "strategy": RolloutStrategy.CANARY.value,
        "selected_arm": selected_arm,
        "bucket": bucket,
        "candidate_percentage": candidate_percentage,
        "baseline_version_id": str(baseline.id),
        "candidate_version_id": str(active_version.id),
    }


def _p95_latency(values: list[int]) -> int | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, int((len(sorted_values) * 0.95) - 1)))
    return sorted_values[index]


def list_organizations(session: Session) -> list[Organization]:
    return list(session.scalars(select(Organization).order_by(Organization.created_at.desc())).all())


def list_organizations_for_actor(session: Session, *, actor_user_id: UUID) -> list[Organization]:
    return list(
        session.scalars(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == actor_user_id)
            .distinct()
            .order_by(Organization.created_at.desc())
        ).all()
    )


def _find_membership(
    session: Session,
    *,
    user_id: UUID,
    org_id: UUID,
    project_id: UUID | None,
) -> Membership | None:
    statement = select(Membership).where(Membership.user_id == user_id, Membership.org_id == org_id)
    if project_id is None:
        statement = statement.where(Membership.project_id.is_(None))
    else:
        statement = statement.where(Membership.project_id == project_id)
    return session.scalar(statement)


def _ensure_membership(
    session: Session,
    *,
    user_id: UUID,
    org_id: UUID,
    project_id: UUID | None,
    role: MembershipRole,
) -> Membership:
    existing = _find_membership(session, user_id=user_id, org_id=org_id, project_id=project_id)
    if existing is not None:
        return existing

    membership = Membership(
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        role=role,
    )
    session.add(membership)
    session.flush()
    return membership


def list_actor_memberships(session: Session, *, actor: AuthenticatedActor) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .where(Membership.user_id == actor.user_id)
            .order_by(Membership.org_id, Membership.project_id, Membership.created_at)
        ).all()
    )


def create_organization(
    session: Session,
    payload: OrganizationCreate,
    *,
    actor_user_id: UUID | None,
) -> Organization:
    existing = session.scalar(select(Organization).where(Organization.slug == payload.slug))
    if existing is not None:
        raise ConflictError(f"organization slug '{payload.slug}' already exists")

    organization = Organization(name=payload.name, slug=payload.slug)
    session.add(organization)
    session.flush()
    if actor_user_id is not None:
        _ensure_membership(
            session,
            user_id=actor_user_id,
            org_id=organization.id,
            project_id=None,
            role=MembershipRole.ORG_ADMIN,
        )

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=organization.id,
        project_id=None,
        action="organization.create",
        resource_type="organization",
        resource_id=organization.id,
        before_json=None,
        after_json={"name": organization.name, "slug": organization.slug},
    )
    return organization


def list_projects(session: Session, *, org_id: UUID) -> list[Project]:
    return list(
        session.scalars(
            select(Project).where(Project.org_id == org_id).order_by(Project.created_at.desc())
        ).all()
    )


def create_project(
    session: Session,
    *,
    org_id: UUID,
    payload: ProjectCreate,
    actor_user_id: UUID | None,
) -> Project:
    _first_or_404(session, select(Organization).where(Organization.id == org_id), "organization not found")

    existing = session.scalar(
        select(Project).where(Project.org_id == org_id, Project.slug == payload.slug)
    )
    if existing is not None:
        raise ConflictError(f"project slug '{payload.slug}' already exists in organization")

    project = Project(
        org_id=org_id,
        name=payload.name,
        slug=payload.slug,
        environment=payload.environment,
    )
    session.add(project)
    session.flush()
    if actor_user_id is not None:
        _ensure_membership(
            session,
            user_id=actor_user_id,
            org_id=org_id,
            project_id=project.id,
            role=MembershipRole.PROJECT_ADMIN,
        )

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=org_id,
        project_id=project.id,
        action="project.create",
        resource_type="project",
        resource_id=project.id,
        before_json=None,
        after_json={"name": project.name, "slug": project.slug, "environment": project.environment.value},
    )
    return project


def list_workflows(session: Session, *, project_id: UUID) -> list[Workflow]:
    return list(
        session.scalars(
            select(Workflow).where(Workflow.project_id == project_id).order_by(Workflow.created_at.desc())
        ).all()
    )


def list_org_memberships(session: Session, *, org_id: UUID) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .where(Membership.org_id == org_id, Membership.project_id.is_(None))
            .order_by(Membership.created_at.desc())
        ).all()
    )


def list_project_memberships(session: Session, *, project_id: UUID) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .where(Membership.project_id == project_id)
            .order_by(Membership.created_at.desc())
        ).all()
    )


def create_org_membership(
    session: Session,
    *,
    org_id: UUID,
    payload: MembershipCreate,
    actor_user_id: UUID | None,
) -> Membership:
    _first_or_404(session, select(Organization).where(Organization.id == org_id), "organization not found")
    existing = _find_membership(session, user_id=payload.user_id, org_id=org_id, project_id=None)
    if existing is not None:
        raise ConflictError("organization membership already exists for this user")

    membership = Membership(
        user_id=payload.user_id,
        org_id=org_id,
        project_id=None,
        role=payload.role,
    )
    session.add(membership)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=org_id,
        project_id=None,
        action="membership.create",
        resource_type="membership",
        resource_id=membership.id,
        before_json=None,
        after_json={
            "user_id": str(membership.user_id),
            "role": membership.role.value,
            "scope": "organization",
        },
    )
    return membership


def create_project_membership(
    session: Session,
    *,
    project_id: UUID,
    payload: MembershipCreate,
    actor_user_id: UUID | None,
) -> Membership:
    project = _first_or_404(session, select(Project).where(Project.id == project_id), "project not found")
    existing = _find_membership(session, user_id=payload.user_id, org_id=project.org_id, project_id=project_id)
    if existing is not None:
        raise ConflictError("project membership already exists for this user")

    membership = Membership(
        user_id=payload.user_id,
        org_id=project.org_id,
        project_id=project_id,
        role=payload.role,
    )
    session.add(membership)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        project_id=project_id,
        action="membership.create",
        resource_type="membership",
        resource_id=membership.id,
        before_json=None,
        after_json={
            "user_id": str(membership.user_id),
            "role": membership.role.value,
            "scope": "project",
        },
    )
    return membership


def list_connectors(session: Session, *, project_id: UUID) -> list[Connector]:
    return list(
        session.scalars(
            select(Connector)
            .where(Connector.project_id == project_id)
            .order_by(Connector.created_at.desc())
        ).all()
    )


def create_connector(
    session: Session,
    *,
    project_id: UUID,
    payload: ConnectorCreate,
    actor_user_id: UUID | None,
) -> Connector:
    project = _first_or_404(session, select(Project).where(Project.id == project_id), "project not found")
    connector = Connector(
        org_id=None,
        project_id=project_id,
        name=payload.name,
        connector_type=payload.connector_type,
        auth_mode=payload.auth_mode,
        scopes_json=list(payload.scopes),
        status=payload.status,
        owner_user_id=actor_user_id,
    )
    session.add(connector)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        project_id=project_id,
        action="connector.create",
        resource_type="connector",
        resource_id=connector.id,
        before_json=None,
        after_json={
            "name": connector.name,
            "connector_type": connector.connector_type.value,
            "auth_mode": connector.auth_mode.value,
            "status": connector.status.value,
        },
    )
    return connector


def get_connector(session: Session, *, project_id: UUID, connector_id: UUID) -> Connector:
    return _first_or_404(
        session,
        select(Connector).where(Connector.project_id == project_id, Connector.id == connector_id),
        "connector not found",
    )


def list_audit_events(
    session: Session,
    *,
    project_id: UUID,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    limit: int = 50,
) -> list[AuditEvent]:
    statement = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if action is not None:
        statement = statement.where(AuditEvent.action == action)
    if resource_type is not None:
        statement = statement.where(AuditEvent.resource_type == resource_type)
    if resource_id is not None:
        statement = statement.where(AuditEvent.resource_id == resource_id)
    if actor_user_id is not None:
        statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
    return list(session.scalars(statement.order_by(AuditEvent.created_at.desc()).limit(limit)).all())


def list_tool_definitions(session: Session, *, project_id: UUID, connector_id: UUID) -> list[ToolDefinition]:
    get_connector(session, project_id=project_id, connector_id=connector_id)
    return list(
        session.scalars(
            select(ToolDefinition)
            .where(ToolDefinition.connector_id == connector_id)
            .order_by(ToolDefinition.name)
        ).all()
    )


def create_tool_definition(
    session: Session,
    *,
    project_id: UUID,
    connector_id: UUID,
    payload: ToolDefinitionCreate,
    actor_user_id: UUID | None,
) -> ToolDefinition:
    connector = get_connector(session, project_id=project_id, connector_id=connector_id)
    existing = session.scalar(
        select(ToolDefinition).where(
            ToolDefinition.connector_id == connector_id,
            ToolDefinition.name == payload.name,
        )
    )
    if existing is not None:
        raise ConflictError("tool definition already exists for this connector")

    tool = ToolDefinition(
        connector_id=connector_id,
        name=payload.name,
        description=payload.description,
        risk_level=payload.risk_level,
        input_schema_json=payload.input_schema,
        output_schema_json=payload.output_schema,
        is_mutating=payload.is_mutating,
    )
    session.add(tool)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=connector.org_id,
        project_id=project_id,
        action="tool_definition.create",
        resource_type="tool_definition",
        resource_id=tool.id,
        before_json=None,
        after_json={
            "connector_id": str(connector_id),
            "name": tool.name,
            "risk_level": tool.risk_level.value,
            "is_mutating": tool.is_mutating,
        },
    )
    return tool


def list_datasets(session: Session, *, project_id: UUID) -> list[Dataset]:
    return list(
        session.scalars(
            select(Dataset)
            .where(Dataset.project_id == project_id)
            .order_by(Dataset.created_at.desc())
        ).all()
    )


def get_dataset(session: Session, *, project_id: UUID, dataset_id: UUID) -> Dataset:
    return _first_or_404(
        session,
        select(Dataset).where(Dataset.project_id == project_id, Dataset.id == dataset_id),
        "dataset not found",
    )


def create_dataset(
    session: Session,
    *,
    project_id: UUID,
    payload: DatasetCreate,
    actor_user_id: UUID | None,
) -> Dataset:
    project = _first_or_404(session, select(Project).where(Project.id == project_id), "project not found")
    existing = session.scalar(
        select(Dataset).where(
            Dataset.project_id == project_id,
            Dataset.name == payload.name,
            Dataset.version == payload.version,
        )
    )
    if existing is not None:
        raise ConflictError("dataset name and version already exist in this project")

    dataset = Dataset(
        project_id=project_id,
        name=payload.name,
        version=payload.version,
        description=payload.description,
        created_by=actor_user_id,
    )
    session.add(dataset)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        project_id=project_id,
        action="dataset.create",
        resource_type="dataset",
        resource_id=dataset.id,
        before_json=None,
        after_json={"name": dataset.name, "version": dataset.version},
    )
    return dataset


def list_eval_cases(session: Session, *, project_id: UUID, dataset_id: UUID) -> list[EvalCase]:
    get_dataset(session, project_id=project_id, dataset_id=dataset_id)
    return list(
        session.scalars(
            select(EvalCase)
            .where(EvalCase.dataset_id == dataset_id)
            .order_by(EvalCase.created_at)
        ).all()
    )


def create_eval_case(
    session: Session,
    *,
    project_id: UUID,
    dataset_id: UUID,
    payload: EvalCaseCreate,
) -> EvalCase:
    get_dataset(session, project_id=project_id, dataset_id=dataset_id)
    eval_case = EvalCase(
        dataset_id=dataset_id,
        input_json=payload.input_payload,
        expected_json=payload.expected,
        tags_json=list(payload.tags),
    )
    session.add(eval_case)
    session.flush()
    return eval_case


def list_eval_runs(session: Session, *, project_id: UUID) -> list[EvalRun]:
    return list(
        session.scalars(
            select(EvalRun)
            .join(Dataset, Dataset.id == EvalRun.dataset_id)
            .where(Dataset.project_id == project_id)
            .order_by(EvalRun.created_at.desc())
        ).all()
    )


def get_eval_run(session: Session, *, project_id: UUID, eval_run_id: UUID) -> EvalRun:
    return _first_or_404(
        session,
        select(EvalRun)
        .join(Dataset, Dataset.id == EvalRun.dataset_id)
        .where(Dataset.project_id == project_id, EvalRun.id == eval_run_id),
        "eval run not found",
    )


def enqueue_eval_run(
    session: Session,
    *,
    project_id: UUID,
    eval_run_id: UUID,
    actor_user_id: UUID | None,
) -> EvalRun:
    eval_run = get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id)
    if eval_run.status != EvalRunStatus.QUEUED:
        raise ConflictError("only queued eval runs can be enqueued")
    project = _first_or_404(session, select(Project).where(Project.id == project_id), "project not found")
    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        project_id=project_id,
        action="eval_run.enqueue",
        resource_type="eval_run",
        resource_id=eval_run.id,
        before_json=None,
        after_json={
            "status": eval_run.status.value,
            "workflow_version_id": str(eval_run.workflow_version_id),
            "baseline_version_id": str(eval_run.baseline_version_id) if eval_run.baseline_version_id else None,
        },
    )
    return eval_run


def create_eval_run(
    session: Session,
    *,
    project_id: UUID,
    payload: EvalRunCreate,
    actor_user_id: UUID | None,
) -> EvalRun:
    dataset = get_dataset(session, project_id=project_id, dataset_id=payload.dataset_id)
    version = _first_or_404(
        session,
        select(WorkflowVersion).options(joinedload(WorkflowVersion.workflow)).where(
            WorkflowVersion.id == payload.workflow_version_id,
        ),
        "workflow version not found",
    )
    if version.workflow.project_id != project_id:
        raise ConflictError("workflow version does not belong to the requested project")
    if version.status != WorkflowVersionStatus.PUBLISHED:
        raise ConflictError("eval runs require a published workflow version")

    if payload.baseline_version_id is not None:
        baseline = _first_or_404(
            session,
            select(WorkflowVersion).options(joinedload(WorkflowVersion.workflow)).where(
                WorkflowVersion.id == payload.baseline_version_id,
            ),
            "baseline workflow version not found",
        )
        if baseline.workflow.project_id != project_id:
            raise ConflictError("baseline version does not belong to the requested project")

    eval_run = EvalRun(
        dataset_id=dataset.id,
        workflow_version_id=version.id,
        baseline_version_id=payload.baseline_version_id,
        status=EvalRunStatus.QUEUED,
        summary_json={},
        started_at=None,
        ended_at=None,
    )
    session.add(eval_run)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=version.workflow.project.org_id,
        project_id=project_id,
        action="eval_run.create",
        resource_type="eval_run",
        resource_id=eval_run.id,
        before_json=None,
        after_json={
            "dataset_id": str(dataset.id),
            "workflow_version_id": str(version.id),
            "status": eval_run.status.value,
        },
    )
    return eval_run


def mark_eval_run_running(session: Session, *, project_id: UUID, eval_run_id: UUID) -> EvalRun:
    eval_run = get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id)
    if eval_run.status != EvalRunStatus.QUEUED:
        raise ConflictError("only queued eval runs can start")
    eval_run.status = EvalRunStatus.RUNNING
    eval_run.started_at = utcnow()
    session.flush()
    return eval_run


def finish_eval_run(
    session: Session,
    *,
    project_id: UUID,
    eval_run_id: UUID,
    status: EvalRunStatus,
    summary: dict,
) -> EvalRun:
    if status not in {EvalRunStatus.SUCCEEDED, EvalRunStatus.FAILED}:
        raise ConflictError("eval run can only finish as succeeded or failed")
    eval_run = get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id)
    eval_run.status = status
    eval_run.summary_json = summary
    eval_run.ended_at = utcnow()
    session.flush()
    return eval_run


def list_eval_case_results(session: Session, *, project_id: UUID, eval_run_id: UUID) -> list[EvalCaseResult]:
    get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id)
    return list(
        session.scalars(
            select(EvalCaseResult)
            .where(EvalCaseResult.eval_run_id == eval_run_id)
            .order_by(EvalCaseResult.created_at)
        ).all()
    )


def create_eval_case_result(
    session: Session,
    *,
    project_id: UUID,
    eval_run_id: UUID,
    eval_case_id: UUID,
    run_id: UUID | None,
    status: EvalCaseStatus,
    scores: dict,
    output: dict | None,
    trace_grade: dict | None,
    error: dict | None,
) -> EvalCaseResult:
    get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id)
    existing = session.scalar(
        select(EvalCaseResult).where(
            EvalCaseResult.eval_run_id == eval_run_id,
            EvalCaseResult.eval_case_id == eval_case_id,
        )
    )
    if existing is not None:
        raise ConflictError("eval case result already exists")

    result = EvalCaseResult(
        eval_run_id=eval_run_id,
        eval_case_id=eval_case_id,
        run_id=run_id,
        status=status,
        scores_json=scores,
        output_json=output,
        trace_grade_json=trace_grade,
        error_json=error,
    )
    session.add(result)
    session.flush()
    return result


def create_workflow(
    session: Session,
    *,
    project_id: UUID,
    payload: WorkflowCreate,
    actor_user_id: UUID | None,
) -> Workflow:
    project = _first_or_404(session, select(Project).where(Project.id == project_id), "project not found")

    existing = session.scalar(
        select(Workflow).where(Workflow.project_id == project_id, Workflow.slug == payload.slug)
    )
    if existing is not None:
        raise ConflictError(f"workflow slug '{payload.slug}' already exists in project")

    workflow = Workflow(
        project_id=project_id,
        active_version_id=None,
        slug=payload.slug,
        name=payload.name,
        domain=payload.domain,
        description=payload.description,
    )
    session.add(workflow)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        project_id=project_id,
        action="workflow.create",
        resource_type="workflow",
        resource_id=workflow.id,
        before_json=None,
        after_json={"slug": workflow.slug, "name": workflow.name, "domain": workflow.domain},
    )
    return workflow


def list_workflow_versions(session: Session, *, workflow_id: UUID) -> list[WorkflowVersion]:
    return list(
        session.scalars(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.created_at.desc())
        ).all()
    )


def create_workflow_version(
    session: Session,
    *,
    workflow_id: UUID,
    payload: WorkflowVersionCreate,
    actor_user_id: UUID | None,
) -> WorkflowVersion:
    workflow = _first_or_404(
        session,
        select(Workflow).options(joinedload(Workflow.project)).where(Workflow.id == workflow_id),
        "workflow not found",
    )

    existing = session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version == payload.version,
        )
    )
    if existing is not None:
        raise ConflictError(f"workflow version '{payload.version}' already exists")

    version = WorkflowVersion(
        workflow_id=workflow_id,
        version=payload.version,
        status=WorkflowVersionStatus.DRAFT,
        prompt_template=payload.prompt_template,
        input_schema_json=payload.input_schema,
        output_schema_json=payload.output_schema,
        model_config_json=payload.model_config_payload.model_dump(mode="json", exclude_none=True),
        policy_pack_json=[policy.model_dump(mode="json", exclude_none=True) for policy in payload.policy_pack],
        tool_set_json=[tool.model_dump(mode="json", exclude_none=True) for tool in payload.tool_set],
        guardrails_json=list(payload.guardrails),
        rollout_config_json=(
            payload.rollout_config.model_dump(mode="json", exclude_none=True) if payload.rollout_config else None
        ),
        eval_dataset_bindings_json=[str(dataset_id) for dataset_id in payload.eval_dataset_bindings],
        created_by=payload.created_by or actor_user_id,
    )
    session.add(version)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id or payload.created_by,
        org_id=workflow.project.org_id,
        project_id=workflow.project_id,
        action="workflow_version.create",
        resource_type="workflow_version",
        resource_id=version.id,
        before_json=None,
        after_json={"workflow_id": str(workflow_id), **_workflow_version_snapshot(version)},
    )
    return version


def get_workflow_version(session: Session, *, workflow_version_id: UUID) -> WorkflowVersion:
    return _first_or_404(
        session,
        select(WorkflowVersion).where(WorkflowVersion.id == workflow_version_id),
        "workflow version not found",
    )


def update_workflow_version(
    session: Session,
    *,
    workflow_version_id: UUID,
    payload: WorkflowVersionUpdate,
    actor_user_id: UUID | None,
) -> WorkflowVersion:
    version = _first_or_404(
        session,
        select(WorkflowVersion)
        .options(joinedload(WorkflowVersion.workflow).joinedload(Workflow.project))
        .where(WorkflowVersion.id == workflow_version_id),
        "workflow version not found",
    )
    if version.status != WorkflowVersionStatus.DRAFT:
        raise ConflictError("only draft workflow versions can be updated")

    if payload.version is not None and payload.version != version.version:
        existing = session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == version.workflow_id,
                WorkflowVersion.version == payload.version,
                WorkflowVersion.id != workflow_version_id,
            )
        )
        if existing is not None:
            raise ConflictError(f"workflow version '{payload.version}' already exists")

    before_snapshot = _workflow_version_snapshot(version)
    changed_fields: list[str] = []

    if payload.version is not None:
        version.version = payload.version
        changed_fields.append("version")
    if payload.prompt_template is not None:
        version.prompt_template = payload.prompt_template
        changed_fields.append("prompt_template")
    if payload.input_schema is not None:
        version.input_schema_json = payload.input_schema
        changed_fields.append("input_schema")
    if payload.output_schema is not None:
        version.output_schema_json = payload.output_schema
        changed_fields.append("output_schema")
    if payload.model_config_payload is not None:
        version.model_config_json = payload.model_config_payload.model_dump(mode="json", exclude_none=True)
        changed_fields.append("model_config")
    if payload.policy_pack is not None:
        version.policy_pack_json = [policy.model_dump(mode="json", exclude_none=True) for policy in payload.policy_pack]
        changed_fields.append("policy_pack")
    if payload.tool_set is not None:
        version.tool_set_json = [tool.model_dump(mode="json", exclude_none=True) for tool in payload.tool_set]
        changed_fields.append("tool_set")
    if payload.guardrails is not None:
        version.guardrails_json = list(payload.guardrails)
        changed_fields.append("guardrails")
    if payload.rollout_config is not None:
        version.rollout_config_json = payload.rollout_config.model_dump(mode="json", exclude_none=True)
        changed_fields.append("rollout_config")
    if payload.eval_dataset_bindings is not None:
        version.eval_dataset_bindings_json = [str(dataset_id) for dataset_id in payload.eval_dataset_bindings]
        changed_fields.append("eval_dataset_bindings")

    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=version.workflow.project.org_id,
        project_id=version.workflow.project_id,
        action="workflow_version.update",
        resource_type="workflow_version",
        resource_id=version.id,
        before_json=before_snapshot,
        after_json={**_workflow_version_snapshot(version), "changed_fields": changed_fields},
    )
    return version


def publish_workflow_version(
    session: Session,
    *,
    workflow_version_id: UUID,
    payload: PublishWorkflowVersionRequest,
    actor_user_id: UUID | None,
) -> WorkflowVersion:
    version = _first_or_404(
        session,
        select(WorkflowVersion)
        .options(joinedload(WorkflowVersion.workflow).joinedload(Workflow.project))
        .where(WorkflowVersion.id == workflow_version_id),
        "workflow version not found",
    )
    if version.status != WorkflowVersionStatus.DRAFT:
        raise ConflictError("only draft workflow versions can be published")

    validate_workflow_definition(build_workflow_definition_document(version.workflow, version))
    before_snapshot = _workflow_version_snapshot(version)

    version.status = WorkflowVersionStatus.PUBLISHED
    version.published_at = utcnow()
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id or payload.published_by,
        org_id=version.workflow.project.org_id,
        project_id=version.workflow.project_id,
        action="workflow_version.publish",
        resource_type="workflow_version",
        resource_id=version.id,
        before_json=before_snapshot,
        after_json={
            **_workflow_version_snapshot(version),
            "published_at": version.published_at.isoformat(),
        },
    )
    return version


def set_active_workflow_version(
    session: Session,
    *,
    workflow_id: UUID,
    payload: SetActiveWorkflowVersionRequest,
    actor_user_id: UUID | None,
) -> Workflow:
    workflow = _first_or_404(
        session,
        select(Workflow).options(joinedload(Workflow.project)).where(Workflow.id == workflow_id),
        "workflow not found",
    )
    version = _first_or_404(
        session,
        select(WorkflowVersion).where(WorkflowVersion.id == payload.workflow_version_id),
        "workflow version not found",
    )
    if version.workflow_id != workflow.id:
        raise ConflictError("workflow version does not belong to this workflow")
    if version.status != WorkflowVersionStatus.PUBLISHED:
        raise ConflictError("only published workflow versions can be activated")

    before_json = {"active_version_id": str(workflow.active_version_id) if workflow.active_version_id else None}
    workflow.active_version_id = version.id
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=workflow.project.org_id,
        project_id=workflow.project_id,
        action="workflow.active_version.set",
        resource_type="workflow",
        resource_id=workflow.id,
        before_json=before_json,
        after_json={"active_version_id": str(version.id), "version": version.version},
    )
    return workflow


def activate_workflow_rollout(
    session: Session,
    *,
    workflow_id: UUID,
    payload: ActivateWorkflowRolloutRequest,
    actor_user_id: UUID | None,
) -> Workflow:
    workflow = _first_or_404(
        session,
        select(Workflow).options(joinedload(Workflow.project)).where(Workflow.id == workflow_id),
        "workflow not found",
    )
    candidate = _first_or_404(
        session,
        select(WorkflowVersion).where(WorkflowVersion.id == payload.candidate_version_id),
        "candidate workflow version not found",
    )
    if candidate.workflow_id != workflow.id:
        raise ConflictError("candidate version does not belong to this workflow")
    if candidate.status != WorkflowVersionStatus.PUBLISHED:
        raise ConflictError("only published workflow versions can be activated for rollout")

    config = candidate.rollout_config_json or {}
    if config.get("strategy") != RolloutStrategy.CANARY.value:
        raise ConflictError("candidate version must define a canary rollout config")
    if config.get("candidate_version") != candidate.version:
        raise ConflictError("rollout candidate_version must match the candidate workflow version")
    traffic_split = config.get("traffic_split") or {}
    candidate_percentage = int(traffic_split.get("candidate") or 0)
    baseline_percentage = int(traffic_split.get("baseline") or 0)
    if candidate_percentage < 0 or baseline_percentage < 0 or candidate_percentage + baseline_percentage != 100:
        raise ConflictError("rollout traffic split must add up to 100")

    baseline_version = config.get("baseline_version")
    if not baseline_version:
        raise ConflictError("rollout baseline_version is required")
    baseline = _get_published_workflow_version_by_version(
        session,
        workflow_id=workflow.id,
        version=str(baseline_version),
    )
    if baseline is None:
        raise ConflictError("rollout baseline version must be published")
    if baseline.id == candidate.id:
        raise ConflictError("rollout baseline and candidate must be different versions")

    before_json = {"active_version_id": str(workflow.active_version_id) if workflow.active_version_id else None}
    workflow.active_version_id = candidate.id
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=workflow.project.org_id,
        project_id=workflow.project_id,
        action="workflow.rollout.activate",
        resource_type="workflow",
        resource_id=workflow.id,
        before_json=before_json,
        after_json={
            "active_version_id": str(candidate.id),
            "baseline_version_id": str(baseline.id),
            "candidate_version_id": str(candidate.id),
            "traffic_split": traffic_split,
        },
    )
    return workflow


def monitor_workflow_rollout(
    session: Session,
    *,
    workflow_id: UUID,
    actor_user_id: UUID | None,
) -> RolloutMonitorRead:
    workflow = _first_or_404(
        session,
        select(Workflow).options(joinedload(Workflow.project)).where(Workflow.id == workflow_id),
        "workflow not found",
    )
    if workflow.active_version_id is None:
        return RolloutMonitorRead(workflow_id=workflow.id, decision="no_active_version")

    candidate = session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == workflow.active_version_id,
            WorkflowVersion.workflow_id == workflow.id,
            WorkflowVersion.status == WorkflowVersionStatus.PUBLISHED,
        )
    )
    if candidate is None:
        return RolloutMonitorRead(workflow_id=workflow.id, active_version_id=workflow.active_version_id, decision="inactive")

    config = candidate.rollout_config_json or {}
    if config.get("strategy") != RolloutStrategy.CANARY.value or config.get("candidate_version") != candidate.version:
        return RolloutMonitorRead(
            workflow_id=workflow.id,
            active_version_id=candidate.id,
            candidate_version_id=candidate.id,
            decision="no_active_rollout",
        )

    baseline_version = config.get("baseline_version")
    baseline = (
        _get_published_workflow_version_by_version(session, workflow_id=workflow.id, version=str(baseline_version))
        if baseline_version
        else None
    )
    if baseline is None:
        raise ConflictError("active rollout baseline version is not published")

    candidate_runs = list(
        session.scalars(
            select(Run).where(
                Run.project_id == workflow.project_id,
                Run.workflow_version_id == candidate.id,
                Run.status.in_(TERMINAL_RUN_STATUSES),
            )
        ).all()
    )
    baseline_runs = list(
        session.scalars(
            select(Run).where(
                Run.project_id == workflow.project_id,
                Run.workflow_version_id == baseline.id,
                Run.status.in_(TERMINAL_RUN_STATUSES),
            )
        ).all()
    )

    candidate_failure_rate = (
        len([run for run in candidate_runs if run.status != RunStatus.SUCCEEDED]) / len(candidate_runs)
        if candidate_runs
        else None
    )
    baseline_failure_rate = (
        len([run for run in baseline_runs if run.status != RunStatus.SUCCEEDED]) / len(baseline_runs)
        if baseline_runs
        else None
    )
    candidate_p95_latency_ms = _p95_latency([run.latency_ms for run in candidate_runs if run.latency_ms is not None])
    baseline_p95_latency_ms = _p95_latency([run.latency_ms for run in baseline_runs if run.latency_ms is not None])

    thresholds = config.get("rollback_thresholds") or {}
    breaches: list[str] = []
    schema_failure_rate_threshold = thresholds.get("schema_failure_rate")
    if (
        schema_failure_rate_threshold is not None
        and candidate_failure_rate is not None
        and candidate_failure_rate > float(schema_failure_rate_threshold)
    ):
        breaches.append("schema_failure_rate")
    p95_latency_threshold = thresholds.get("p95_latency_ms")
    if (
        p95_latency_threshold is not None
        and candidate_p95_latency_ms is not None
        and candidate_p95_latency_ms > int(p95_latency_threshold)
    ):
        breaches.append("p95_latency_ms")

    decision = "healthy"
    if breaches:
        before_json = {"active_version_id": str(workflow.active_version_id)}
        workflow.active_version_id = baseline.id
        session.flush()
        decision = "rolled_back"
        record_audit_event(
            session,
            actor_user_id=actor_user_id,
            org_id=workflow.project.org_id,
            project_id=workflow.project_id,
            action="workflow.rollout.rollback",
            resource_type="workflow",
            resource_id=workflow.id,
            before_json=before_json,
            after_json={
                "active_version_id": str(baseline.id),
                "candidate_version_id": str(candidate.id),
                "thresholds_breached": breaches,
            },
        )

    return RolloutMonitorRead(
        workflow_id=workflow.id,
        active_version_id=workflow.active_version_id,
        baseline_version_id=baseline.id,
        candidate_version_id=candidate.id,
        decision=decision,
        thresholds_breached=breaches,
        candidate_runs=len(candidate_runs),
        baseline_runs=len(baseline_runs),
        candidate_failure_rate=candidate_failure_rate,
        baseline_failure_rate=baseline_failure_rate,
        candidate_p95_latency_ms=candidate_p95_latency_ms,
        baseline_p95_latency_ms=baseline_p95_latency_ms,
    )


def list_runs(session: Session, *, project_id: UUID) -> list[Run]:
    return list(
        session.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())).all()
    )


def submit_run(
    session: Session,
    *,
    project_id: UUID,
    payload: RunSubmitRequest,
    actor_user_id: UUID | None,
) -> Run:
    version = _first_or_404(
        session,
        select(WorkflowVersion)
        .options(joinedload(WorkflowVersion.workflow).joinedload(Workflow.project))
        .where(WorkflowVersion.id == payload.workflow_version_id),
        "workflow version not found",
    )

    if version.workflow.project_id != project_id:
        raise ConflictError("workflow version does not belong to the requested project")
    if version.status != WorkflowVersionStatus.PUBLISHED:
        raise ConflictError("runs can only be created from published workflow versions")

    return _create_run_for_version(
        session,
        project_id=project_id,
        version=version,
        input_payload=payload.input_payload,
        triggered_by=payload.triggered_by,
        actor_user_id=actor_user_id,
    )


def submit_workflow_run(
    session: Session,
    *,
    project_id: UUID,
    workflow_slug: str,
    payload: WorkflowRunSubmitRequest,
    actor_user_id: UUID | None,
) -> Run:
    workflow = _first_or_404(
        session,
        select(Workflow).where(Workflow.project_id == project_id, Workflow.slug == workflow_slug),
        "workflow not found",
    )
    if workflow.active_version_id is not None:
        version = session.scalar(
            select(WorkflowVersion)
            .options(joinedload(WorkflowVersion.workflow).joinedload(Workflow.project))
            .where(
                WorkflowVersion.id == workflow.active_version_id,
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.status == WorkflowVersionStatus.PUBLISHED,
            )
        )
    else:
        version = session.scalar(
            select(WorkflowVersion)
            .options(joinedload(WorkflowVersion.workflow).joinedload(Workflow.project))
            .where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.status == WorkflowVersionStatus.PUBLISHED,
            )
            .order_by(WorkflowVersion.published_at.desc(), WorkflowVersion.created_at.desc())
        )
    if version is None:
        raise NotFoundError("published workflow version not found")
    routing_context = None
    if workflow.active_version_id is not None:
        version, routing_context = _resolve_active_rollout_version(
            session,
            workflow=workflow,
            active_version=version,
            input_payload=payload.input_payload,
        )

    return _create_run_for_version(
        session,
        project_id=project_id,
        version=version,
        input_payload=payload.input_payload,
        triggered_by=payload.triggered_by,
        actor_user_id=actor_user_id,
        routing_context=routing_context,
    )


def get_run(session: Session, *, project_id: UUID, run_id: UUID) -> Run:
    return _first_or_404(
        session,
        select(Run).where(Run.project_id == project_id, Run.id == run_id),
        "run not found",
    )


def enqueue_run(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    actor_user_id: UUID | None,
) -> Run:
    run = get_run(session, project_id=project_id, run_id=run_id)
    if run.status not in {RunStatus.QUEUED, RunStatus.RESUMED}:
        raise ConflictError("only queued or resumed runs can be enqueued")
    project = _first_or_404(session, select(Project).where(Project.id == project_id), "project not found")
    record_audit_event(
        session,
        actor_user_id=actor_user_id,
        org_id=project.org_id,
        project_id=project_id,
        action="run.enqueue",
        resource_type="run",
        resource_id=run.id,
        before_json=None,
        after_json={"status": run.status.value, "workflow_version_id": str(run.workflow_version_id)},
    )
    return run


def transition_run_status(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    payload: RunTransitionRequest,
) -> Run:
    run = get_run(session, project_id=project_id, run_id=run_id)
    _ensure_run_transition_allowed(current_status=run.status, next_status=payload.status)
    if payload.final_output is not None and payload.status != RunStatus.SUCCEEDED:
        raise ConflictError("final_output can only be set when a run succeeds")

    now = utcnow()
    run.status = payload.status
    if payload.status == RunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    if payload.status in TERMINAL_RUN_STATUSES and run.ended_at is None:
        run.ended_at = now
        if run.started_at is not None and payload.latency_ms is None:
            run.latency_ms = _latency_ms_between(run.started_at, run.ended_at)

    if payload.final_output is not None:
        run.final_output_json = payload.final_output
    if payload.latency_ms is not None:
        run.latency_ms = payload.latency_ms
    if payload.cost_usd is not None:
        run.cost_usd = payload.cost_usd
    if payload.tokens_input is not None:
        run.tokens_input = payload.tokens_input
    if payload.tokens_output is not None:
        run.tokens_output = payload.tokens_output

    session.flush()
    return run


def list_trace_spans(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    span_type: str | None = None,
    status: SpanStatus | None = None,
) -> list[TraceSpan]:
    get_run(session, project_id=project_id, run_id=run_id)
    statement = select(TraceSpan).where(TraceSpan.project_id == project_id, TraceSpan.run_id == run_id)
    if span_type is not None:
        statement = statement.where(TraceSpan.span_type == span_type)
    if status is not None:
        statement = statement.where(TraceSpan.status == status)
    return list(
        session.scalars(
            statement.order_by(TraceSpan.started_at, TraceSpan.created_at)
        ).all()
    )


def create_trace_span(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    payload: TraceSpanCreate,
) -> TraceSpan:
    run = get_run(session, project_id=project_id, run_id=run_id)
    existing = session.scalar(
        select(TraceSpan).where(
            TraceSpan.project_id == project_id,
            TraceSpan.run_id == run_id,
            TraceSpan.trace_id == payload.trace_id,
            TraceSpan.span_id == payload.span_id,
        )
    )
    if existing is not None:
        raise ConflictError("trace span already exists")

    span = TraceSpan(
        project_id=project_id,
        workflow_version_id=run.workflow_version_id,
        run_id=run_id,
        trace_id=payload.trace_id,
        span_id=payload.span_id,
        parent_span_id=payload.parent_span_id,
        span_type=payload.span_type,
        name=payload.name,
        status=payload.status,
        started_at=payload.started_at or utcnow(),
        ended_at=payload.ended_at,
        attributes_json=payload.attributes,
        error_json=payload.error,
    )
    session.add(span)
    session.flush()
    return span


def list_tool_calls(session: Session, *, project_id: UUID, run_id: UUID) -> list[ToolCall]:
    get_run(session, project_id=project_id, run_id=run_id)
    return list(
        session.scalars(
            select(ToolCall)
            .where(ToolCall.project_id == project_id, ToolCall.run_id == run_id)
            .order_by(ToolCall.created_at)
        ).all()
    )


def create_tool_call(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    payload: ToolCallCreate,
) -> ToolCall:
    run = get_run(session, project_id=project_id, run_id=run_id)
    if run.status not in ACTIVE_RUN_STATUSES:
        raise ConflictError("tool calls can only be recorded while a run is active")

    tool_call = ToolCall(
        project_id=project_id,
        run_id=run_id,
        span_id=payload.span_id,
        tool_name=payload.tool_name,
        args_json=payload.args,
        status=ToolCallStatus.PROPOSED,
        approval_required=payload.approval_required,
        result_json=None,
        error_json=None,
    )
    session.add(tool_call)
    session.flush()
    return tool_call


def update_tool_call(
    session: Session,
    *,
    project_id: UUID,
    tool_call_id: UUID,
    payload: ToolCallUpdate,
) -> ToolCall:
    tool_call = _first_or_404(
        session,
        select(ToolCall).where(ToolCall.project_id == project_id, ToolCall.id == tool_call_id),
        "tool call not found",
    )
    _ensure_tool_call_transition_allowed(current_status=tool_call.status, next_status=payload.status)
    if payload.result is not None and payload.status != ToolCallStatus.EXECUTED:
        raise ConflictError("tool call result can only be set when status is executed")
    if payload.error is not None and payload.status != ToolCallStatus.FAILED:
        raise ConflictError("tool call error can only be set when status is failed")

    tool_call.status = payload.status
    if payload.span_id is not None:
        tool_call.span_id = payload.span_id
    if payload.status == ToolCallStatus.EXECUTED:
        tool_call.result_json = payload.result or {}
        tool_call.error_json = None
    if payload.status == ToolCallStatus.FAILED:
        tool_call.error_json = payload.error or {}
    if payload.status in TERMINAL_TOOL_CALL_STATUSES and payload.status != ToolCallStatus.FAILED:
        tool_call.error_json = None

    session.flush()
    return tool_call


def list_approval_requests(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID | None = None,
    status: ApprovalStatus | None = None,
) -> list[ApprovalRequest]:
    statement = select(ApprovalRequest).where(ApprovalRequest.project_id == project_id)
    if run_id is not None:
        statement = statement.where(ApprovalRequest.run_id == run_id)
    if status is not None:
        statement = statement.where(ApprovalRequest.status == status)
    return list(session.scalars(statement.order_by(ApprovalRequest.requested_at.desc())).all())


def get_approval_request(session: Session, *, project_id: UUID, approval_id: UUID) -> ApprovalRequest:
    return _first_or_404(
        session,
        select(ApprovalRequest).where(
            ApprovalRequest.project_id == project_id,
            ApprovalRequest.id == approval_id,
        ),
        "approval request not found",
    )


def create_approval_request(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    tool_call_id: UUID,
    approver_role: MembershipRole,
    reason: str,
    run_context: dict | None,
    proposed_effect: dict | None,
) -> ApprovalRequest:
    run = get_run(session, project_id=project_id, run_id=run_id)
    tool_call = _first_or_404(
        session,
        select(ToolCall).where(
            ToolCall.project_id == project_id,
            ToolCall.run_id == run_id,
            ToolCall.id == tool_call_id,
        ),
        "tool call not found",
    )
    if tool_call.status != ToolCallStatus.PROPOSED:
        raise ConflictError("approval requests can only be created for proposed tool calls")

    existing = session.scalar(select(ApprovalRequest).where(ApprovalRequest.tool_call_id == tool_call_id))
    if existing is not None:
        raise ConflictError("approval request already exists for this tool call")

    approval = ApprovalRequest(
        project_id=project_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        approver_role=approver_role,
        status=ApprovalStatus.PENDING,
        reason=reason,
        run_context_json=run_context,
        proposed_effect_json=proposed_effect,
    )
    session.add(approval)
    session.flush()

    tool_call.approval_required = True
    tool_call.approval_id = approval.id
    session.flush()

    record_audit_event(
        session,
        actor_user_id=run.triggered_by,
        org_id=run.workflow_version.workflow.project.org_id,
        project_id=project_id,
        action="approval.request",
        resource_type="approval_request",
        resource_id=approval.id,
        before_json=None,
        after_json={
            "run_id": str(run_id),
            "tool_call_id": str(tool_call_id),
            "tool_name": tool_call.tool_name,
            "approver_role": approver_role.value,
            "status": approval.status.value,
        },
    )
    return approval


def decide_approval_request(
    session: Session,
    *,
    project_id: UUID,
    approval_id: UUID,
    status: ApprovalStatus,
    decided_by: UUID,
    decision_note: str | None,
) -> ApprovalRequest:
    if status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
        raise ConflictError("approval decision must be approved or rejected")

    approval = _first_or_404(
        session,
        select(ApprovalRequest)
        .options(joinedload(ApprovalRequest.tool_call))
        .where(ApprovalRequest.project_id == project_id, ApprovalRequest.id == approval_id),
        "approval request not found",
    )
    if approval.status != ApprovalStatus.PENDING:
        raise ConflictError("approval request has already been decided")

    before_json = {
        "status": approval.status.value,
        "decided_by": str(approval.decided_by) if approval.decided_by else None,
    }
    approval.status = status
    approval.decided_at = utcnow()
    approval.decided_by = decided_by
    approval.decision_note = decision_note

    tool_call_status = ToolCallStatus.APPROVED if status == ApprovalStatus.APPROVED else ToolCallStatus.REJECTED
    update_tool_call(
        session,
        project_id=project_id,
        tool_call_id=approval.tool_call_id,
        payload=ToolCallUpdate(status=tool_call_status),
    )

    run = get_run(session, project_id=project_id, run_id=approval.run_id)
    pending_count = session.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            ApprovalRequest.project_id == project_id,
            ApprovalRequest.run_id == approval.run_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    ) or 0
    if pending_count == 0 and run.status == RunStatus.AWAITING_APPROVAL:
        transition_run_status(
            session,
            project_id=project_id,
            run_id=approval.run_id,
            payload=RunTransitionRequest(status=RunStatus.RESUMED),
        )

    record_audit_event(
        session,
        actor_user_id=decided_by,
        org_id=run.workflow_version.workflow.project.org_id,
        project_id=project_id,
        action=f"approval.{status.value}",
        resource_type="approval_request",
        resource_id=approval.id,
        before_json=before_json,
        after_json={
            "status": approval.status.value,
            "decided_by": str(decided_by),
            "tool_call_id": str(approval.tool_call_id),
        },
    )
    return approval
