from __future__ import annotations

from collections.abc import Callable
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from arp_api.dependencies.db import get_db_session
from arp_api.settings import APISettings
from arp_core.application import auth as authz


def get_authenticated_actor(
    request: Request,
    x_actor_user_id: UUID | None = Header(default=None, alias="X-Actor-User-Id"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> authz.AuthenticatedActor:
    settings: APISettings = request.app.state.settings
    if settings.auth_mode == "development_header":
        return authz.require_authenticated_actor(x_actor_user_id)
    if x_api_key is None:
        raise authz.AuthenticationError("missing X-API-Key header")
    for configured_token, user_id in settings.api_tokens.items():
        if compare_digest(configured_token, x_api_key):
            return authz.AuthenticatedActor(user_id=user_id)
    raise authz.AuthenticationError("invalid API key")


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
