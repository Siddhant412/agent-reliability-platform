from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from arp_core.domain.enums import ConnectorAuthMode, ConnectorStatus, ConnectorType, ToolRiskLevel


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    connector_type: ConnectorType = ConnectorType.LOCAL
    auth_mode: ConnectorAuthMode = ConnectorAuthMode.NONE
    scopes: list[str] = Field(default_factory=list)
    status: ConnectorStatus = ConnectorStatus.UNKNOWN


class ConnectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None = None
    project_id: UUID | None = None
    name: str
    connector_type: ConnectorType
    auth_mode: ConnectorAuthMode
    scopes: list[str]
    status: ConnectorStatus
    owner_user_id: UUID | None = None
    created_at: datetime


class ToolDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    risk_level: ToolRiskLevel
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    is_mutating: bool = False


class ToolDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_id: UUID
    name: str
    description: str
    risk_level: ToolRiskLevel
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    is_mutating: bool
    created_at: datetime
