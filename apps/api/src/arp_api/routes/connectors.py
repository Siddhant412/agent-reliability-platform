from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from arp_api.dependencies.auth import get_authenticated_actor, require_project_access
from arp_api.dependencies.db import get_db_session
from arp_core.application import auth as authz
from arp_core.application import services
from arp_core.application.auth import AuthenticatedActor
from arp_core.contracts.serializers import connector_to_read, tool_definition_to_read
from arp_core.contracts.tooling import ConnectorCreate, ConnectorRead, ToolDefinitionCreate, ToolDefinitionRead
from arp_core.domain.enums import ConnectorAuthMode, ConnectorStatus, ConnectorType, ToolRiskLevel
from arp_support_demo.tools import TOOL_METADATA


router = APIRouter(tags=["connectors"])


@router.get("/api/v1/projects/{project_id}/connectors", response_model=list[ConnectorRead])
def list_connectors(
    project_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ConnectorRead]:
    return [connector_to_read(record) for record in services.list_connectors(session, project_id=project_id)]


@router.post(
    "/api/v1/projects/{project_id}/connectors",
    response_model=ConnectorRead,
    status_code=status.HTTP_201_CREATED,
)
def create_connector(
    project_id: UUID,
    payload: ConnectorCreate,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_write_workflows)),
    ],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ConnectorRead:
    connector = services.create_connector(
        session,
        project_id=project_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return connector_to_read(connector)


@router.get(
    "/api/v1/projects/{project_id}/connectors/{connector_id}/tools",
    response_model=list[ToolDefinitionRead],
)
def list_tools(
    project_id: UUID,
    connector_id: UUID,
    _: Annotated[authz.ProjectAccess, Depends(require_project_access(permission=authz.ensure_project_can_read))],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ToolDefinitionRead]:
    return [
        tool_definition_to_read(record)
        for record in services.list_tool_definitions(session, project_id=project_id, connector_id=connector_id)
    ]


@router.post(
    "/api/v1/projects/{project_id}/connectors/{connector_id}/tools",
    response_model=ToolDefinitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tool(
    project_id: UUID,
    connector_id: UUID,
    payload: ToolDefinitionCreate,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_write_workflows)),
    ],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ToolDefinitionRead:
    tool = services.create_tool_definition(
        session,
        project_id=project_id,
        connector_id=connector_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    return tool_definition_to_read(tool)


@router.post(
    "/api/v1/projects/{project_id}/connectors/support-demo/seed",
    response_model=list[ToolDefinitionRead],
)
def seed_support_demo_tools(
    project_id: UUID,
    _: Annotated[
        authz.ProjectAccess,
        Depends(require_project_access(permission=authz.ensure_project_can_write_workflows)),
    ],
    actor: Annotated[AuthenticatedActor, Depends(get_authenticated_actor)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ToolDefinitionRead]:
    connectors = services.list_connectors(session, project_id=project_id)
    connector = next((record for record in connectors if record.name == "Support Demo"), None)
    if connector is None:
        connector = services.create_connector(
            session,
            project_id=project_id,
            payload=ConnectorCreate(
                name="Support Demo",
                connector_type=ConnectorType.LOCAL,
                auth_mode=ConnectorAuthMode.NONE,
                scopes=["support:read", "support:write"],
                status=ConnectorStatus.ACTIVE,
            ),
            actor_user_id=actor.user_id,
        )

    existing_tools = {
        tool.name: tool
        for tool in services.list_tool_definitions(session, project_id=project_id, connector_id=connector.id)
    }
    for metadata in TOOL_METADATA.values():
        if metadata.name in existing_tools:
            continue
        existing_tools[metadata.name] = services.create_tool_definition(
            session,
            project_id=project_id,
            connector_id=connector.id,
            payload=ToolDefinitionCreate(
                name=metadata.name,
                description=metadata.description,
                risk_level=ToolRiskLevel(metadata.risk_level),
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                is_mutating=metadata.is_mutating,
            ),
            actor_user_id=actor.user_id,
        )

    return [
        tool_definition_to_read(record)
        for record in services.list_tool_definitions(session, project_id=project_id, connector_id=connector.id)
    ]
