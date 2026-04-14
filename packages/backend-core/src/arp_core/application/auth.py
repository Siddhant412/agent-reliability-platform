from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from arp_core.application.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from arp_core.domain.enums import MembershipRole
from arp_core.persistence.models import Membership, Project, Workflow, WorkflowVersion


ORG_ADMIN_ROLES = {MembershipRole.PLATFORM_ADMIN, MembershipRole.ORG_ADMIN}
PROJECT_ADMIN_ROLES = ORG_ADMIN_ROLES | {MembershipRole.PROJECT_ADMIN}
WORKFLOW_WRITE_ROLES = PROJECT_ADMIN_ROLES | {MembershipRole.AI_ENGINEER}
RUN_ACCESS_ROLES = {
    MembershipRole.PLATFORM_ADMIN,
    MembershipRole.ORG_ADMIN,
    MembershipRole.PROJECT_ADMIN,
    MembershipRole.AI_ENGINEER,
    MembershipRole.SUPERVISOR,
    MembershipRole.TEAM_LEAD,
    MembershipRole.OPERATOR,
    MembershipRole.ANALYST,
    MembershipRole.API_CLIENT,
}


@dataclass(frozen=True)
class AuthenticatedActor:
    user_id: UUID


@dataclass(frozen=True)
class OrgAccess:
    actor: AuthenticatedActor
    org_id: UUID
    org_roles: frozenset[MembershipRole]
    project_roles: dict[UUID, frozenset[MembershipRole]]

    def can_view_all_projects(self) -> bool:
        return bool(self.org_roles)

    def accessible_project_ids(self) -> set[UUID]:
        return set(self.project_roles.keys())


@dataclass(frozen=True)
class ProjectAccess:
    actor: AuthenticatedActor
    org_id: UUID
    project_id: UUID
    org_roles: frozenset[MembershipRole]
    project_roles: frozenset[MembershipRole]

    def has_any_role(self, allowed_roles: set[MembershipRole]) -> bool:
        return bool(self.org_roles.intersection(allowed_roles) or self.project_roles.intersection(allowed_roles))


@dataclass(frozen=True)
class WorkflowAccess:
    workflow_id: UUID
    project_access: ProjectAccess


@dataclass(frozen=True)
class WorkflowVersionAccess:
    workflow_version_id: UUID
    project_access: ProjectAccess


def require_authenticated_actor(user_id: UUID | None) -> AuthenticatedActor:
    if user_id is None:
        raise AuthenticationError("missing X-Actor-User-Id header")
    return AuthenticatedActor(user_id=user_id)


def resolve_org_access(session: Session, *, actor: AuthenticatedActor, org_id: UUID) -> OrgAccess:
    memberships = list(
        session.scalars(
            select(Membership).where(Membership.user_id == actor.user_id, Membership.org_id == org_id)
        ).all()
    )
    if not memberships:
        raise AuthorizationError("actor does not have access to this organization")

    org_roles = frozenset(membership.role for membership in memberships if membership.project_id is None)
    project_roles: dict[UUID, set[MembershipRole]] = {}
    for membership in memberships:
        if membership.project_id is None:
            continue
        project_roles.setdefault(membership.project_id, set()).add(membership.role)

    return OrgAccess(
        actor=actor,
        org_id=org_id,
        org_roles=org_roles,
        project_roles={project_id: frozenset(roles) for project_id, roles in project_roles.items()},
    )


def resolve_project_access(session: Session, *, actor: AuthenticatedActor, project_id: UUID) -> ProjectAccess:
    project = session.scalar(select(Project).where(Project.id == project_id))
    if project is None:
        raise NotFoundError("project not found")

    memberships = list(
        session.scalars(
            select(Membership).where(
                Membership.user_id == actor.user_id,
                Membership.org_id == project.org_id,
                or_(Membership.project_id.is_(None), Membership.project_id == project_id),
            )
        ).all()
    )
    if not memberships:
        raise AuthorizationError("actor does not have access to this project")

    org_roles = frozenset(membership.role for membership in memberships if membership.project_id is None)
    project_roles = frozenset(
        membership.role for membership in memberships if membership.project_id == project_id
    )
    return ProjectAccess(
        actor=actor,
        org_id=project.org_id,
        project_id=project_id,
        org_roles=org_roles,
        project_roles=project_roles,
    )


def resolve_workflow_access(session: Session, *, actor: AuthenticatedActor, workflow_id: UUID) -> WorkflowAccess:
    workflow = session.scalar(select(Workflow).where(Workflow.id == workflow_id))
    if workflow is None:
        raise NotFoundError("workflow not found")
    return WorkflowAccess(
        workflow_id=workflow_id,
        project_access=resolve_project_access(session, actor=actor, project_id=workflow.project_id),
    )


def resolve_workflow_version_access(
    session: Session,
    *,
    actor: AuthenticatedActor,
    workflow_version_id: UUID,
) -> WorkflowVersionAccess:
    workflow_version = session.scalar(select(WorkflowVersion).where(WorkflowVersion.id == workflow_version_id))
    if workflow_version is None:
        raise NotFoundError("workflow version not found")

    workflow = session.scalar(select(Workflow).where(Workflow.id == workflow_version.workflow_id))
    if workflow is None:
        raise NotFoundError("workflow not found")

    return WorkflowVersionAccess(
        workflow_version_id=workflow_version_id,
        project_access=resolve_project_access(session, actor=actor, project_id=workflow.project_id),
    )


def ensure_org_can_create_project(access: OrgAccess) -> None:
    if not access.org_roles.intersection(ORG_ADMIN_ROLES):
        raise AuthorizationError("actor is not allowed to create projects in this organization")


def ensure_org_can_manage_memberships(access: OrgAccess) -> None:
    if not access.org_roles.intersection(ORG_ADMIN_ROLES):
        raise AuthorizationError("actor is not allowed to manage organization memberships")


def ensure_project_can_manage_memberships(access: ProjectAccess) -> None:
    if not access.has_any_role(PROJECT_ADMIN_ROLES):
        raise AuthorizationError("actor is not allowed to manage project memberships")


def ensure_project_can_read(access: ProjectAccess) -> None:
    if not access.org_roles and not access.project_roles:
        raise AuthorizationError("actor is not allowed to access this project")


def ensure_project_can_write_workflows(access: ProjectAccess) -> None:
    if not access.has_any_role(WORKFLOW_WRITE_ROLES):
        raise AuthorizationError("actor is not allowed to modify workflows in this project")


def ensure_project_can_access_runs(access: ProjectAccess) -> None:
    if not access.has_any_role(RUN_ACCESS_ROLES):
        raise AuthorizationError("actor is not allowed to access runs in this project")
