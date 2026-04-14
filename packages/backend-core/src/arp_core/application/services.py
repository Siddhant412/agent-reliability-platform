from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from arp_core.application.audit import record_audit_event
from arp_core.application.exceptions import ConflictError, NotFoundError
from arp_core.contracts.run import RunSubmitRequest
from arp_core.contracts.tenant import OrganizationCreate, ProjectCreate
from arp_core.contracts.workflow import PublishWorkflowVersionRequest, WorkflowCreate, WorkflowVersionCreate
from arp_core.domain.enums import RunStatus, WorkflowVersionStatus
from arp_core.persistence.base import utcnow
from arp_core.persistence.models import Organization, Project, Run, Workflow, WorkflowVersion


def _first_or_404(session: Session, statement: Select, message: str):
    result = session.scalar(statement)
    if result is None:
        raise NotFoundError(message)
    return result


def list_organizations(session: Session) -> list[Organization]:
    return list(session.scalars(select(Organization).order_by(Organization.created_at.desc())).all())


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
        model_config_json=payload.model_config_payload.model_dump(mode="json"),
        policy_pack_json=[policy.model_dump(mode="json") for policy in payload.policy_pack],
        tool_set_json=[tool.model_dump(mode="json") for tool in payload.tool_set],
        guardrails_json=list(payload.guardrails),
        rollout_config_json=payload.rollout_config.model_dump(mode="json") if payload.rollout_config else None,
        eval_dataset_bindings_json=[str(dataset_id) for dataset_id in payload.eval_dataset_bindings],
        created_by=payload.created_by,
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
        after_json={"workflow_id": str(workflow_id), "version": version.version, "status": version.status.value},
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
        before_json={"status": WorkflowVersionStatus.DRAFT.value},
        after_json={"status": WorkflowVersionStatus.PUBLISHED.value, "published_at": version.published_at.isoformat()},
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
