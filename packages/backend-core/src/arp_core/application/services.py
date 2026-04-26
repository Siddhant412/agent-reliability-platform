from __future__ import annotations

from datetime import datetime
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JSONSchemaValidationError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from arp_core.application.audit import record_audit_event
from arp_core.application.exceptions import ApplicationError, ConflictError, NotFoundError
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.run import (
    RunSubmitRequest,
    RunTransitionRequest,
    ToolCallCreate,
    ToolCallUpdate,
    TraceSpanCreate,
    WorkflowRunSubmitRequest,
)
from arp_core.contracts.tenant import MembershipCreate, OrganizationCreate, ProjectCreate
from arp_core.contracts.workflow import (
    PublishWorkflowVersionRequest,
    WorkflowCreate,
    WorkflowVersionCreate,
    WorkflowVersionUpdate,
)
from arp_core.domain.enums import MembershipRole, RunStatus, ToolCallStatus, WorkflowVersionStatus
from arp_core.persistence.base import utcnow
from arp_core.persistence.models import Membership, Organization, Project, Run, ToolCall, TraceSpan, Workflow, WorkflowVersion
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
        },
    )
    return run


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
        rollout_config_json=payload.rollout_config.model_dump(mode="json") if payload.rollout_config else None,
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
        version.rollout_config_json = payload.rollout_config.model_dump(mode="json")
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

    return _create_run_for_version(
        session,
        project_id=project_id,
        version=version,
        input_payload=payload.input_payload,
        triggered_by=payload.triggered_by,
        actor_user_id=actor_user_id,
    )


def get_run(session: Session, *, project_id: UUID, run_id: UUID) -> Run:
    return _first_or_404(
        session,
        select(Run).where(Run.project_id == project_id, Run.id == run_id),
        "run not found",
    )


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


def list_trace_spans(session: Session, *, project_id: UUID, run_id: UUID) -> list[TraceSpan]:
    get_run(session, project_id=project_id, run_id=run_id)
    return list(
        session.scalars(
            select(TraceSpan)
            .where(TraceSpan.project_id == project_id, TraceSpan.run_id == run_id)
            .order_by(TraceSpan.started_at, TraceSpan.created_at)
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
