from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class ToolGatewayError(Exception):
    def __init__(self, message: str, *, error_type: str = "ToolGatewayError"):
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class ToolExecutionRequest:
    project_id: UUID
    run_id: UUID
    tool_name: str
    args: dict[str, Any]


class ToolGateway(Protocol):
    def execute(self, request: ToolExecutionRequest) -> dict[str, Any]:
        """Execute a tool call and return the provider result."""
        ...


class LocalSupportToolGateway:
    def execute(self, request: ToolExecutionRequest) -> dict[str, Any]:
        from arp_support_demo.tools import SupportToolError, execute_tool

        try:
            return execute_tool(request.tool_name, request.args)
        except SupportToolError as exc:
            raise ToolGatewayError(str(exc), error_type=exc.__class__.__name__) from exc
