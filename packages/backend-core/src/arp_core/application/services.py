from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from arp_core.application.audit import record_audit_event
from arp_core.application.exceptions import ConflictError, NotFoundError
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.run import RunSubmitRequest
from arp_core.contracts.tenant import MembershipCreate, OrganizationCreate, ProjectCreate
from arp_core.contracts.workflow import (
    PublishWorkflowVersionRequest,
    WorkflowCreate,
    WorkflowVersionCreate,
    WorkflowVersionUpdate,
)
from arp_core.domain.enums import MembershipRole, RunStatus, WorkflowVersionStatus
from arp_core.persistence.base import utcnow
from arp_core.persistence.models import Membership, Organization, Project, Run, Workflow, WorkflowVersion
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

    run = Run(
        project_id=project_id,
        workflow_version_id=version.id,
        triggered_by=payload.triggered_by,
        status=RunStatus.QUEUED,
        input_json=payload.input_payload,
        started_at=None,
        ended_at=None,
    )
    session.add(run)
    session.flush()

    record_audit_event(
        session,
        actor_user_id=actor_user_id or payload.triggered_by,
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


def get_run(session: Session, *, project_id: UUID, run_id: UUID) -> Run:
    return _first_or_404(
        session,
        select(Run).where(Run.project_id == project_id, Run.id == run_id),
        "run not found",
    )
