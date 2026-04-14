from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz


def get_authenticated_actor(
    x_actor_user_id: UUID | None = Header(default=None, alias="X-Actor-User-Id"),
) -> authz.AuthenticatedActor:
    return authz.require_authenticated_actor(x_actor_user_id)


def require_org_access(*, permission: Callable[[authz.OrgAccess], None]):
    def dependency(
        org_id: UUID,
        actor: Annotated[authz.AuthenticatedActor, Depends(get_authenticated_actor)],
        session: Annotated[Session, Depends(get_db_session)],
    ) -> authz.OrgAccess:
        access = authz.resolve_org_access(session, actor=actor, org_id=org_id)
        permission(access)
        return access

    return dependency


def require_project_access(*, permission: Callable[[authz.ProjectAccess], None]):
    def dependency(
        project_id: UUID,
        actor: Annotated[authz.AuthenticatedActor, Depends(get_authenticated_actor)],
        session: Annotated[Session, Depends(get_db_session)],
    ) -> authz.ProjectAccess:
        access = authz.resolve_project_access(session, actor=actor, project_id=project_id)
        permission(access)
        return access

    return dependency


def require_workflow_access(*, permission: Callable[[authz.ProjectAccess], None]):
    def dependency(
        workflow_id: UUID,
        actor: Annotated[authz.AuthenticatedActor, Depends(get_authenticated_actor)],
        session: Annotated[Session, Depends(get_db_session)],
    ) -> authz.WorkflowAccess:
        access = authz.resolve_workflow_access(session, actor=actor, workflow_id=workflow_id)
        permission(access.project_access)
        return access

    return dependency


def require_workflow_version_access(*, permission: Callable[[authz.ProjectAccess], None]):
    def dependency(
        workflow_version_id: UUID,
        actor: Annotated[authz.AuthenticatedActor, Depends(get_authenticated_actor)],
        session: Annotated[Session, Depends(get_db_session)],
    ) -> authz.WorkflowVersionAccess:
        access = authz.resolve_workflow_version_access(
            session,
            actor=actor,
            workflow_version_id=workflow_version_id,
        )
        permission(access.project_access)
        return access

    return dependency
