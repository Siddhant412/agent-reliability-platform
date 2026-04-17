from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, ValidationError as JSONSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
import yaml

from arp_core.application.exceptions import ApplicationError
from arp_core.contracts.workflow import WorkflowCreate, WorkflowVersionCreate
from arp_core.persistence.models import Workflow, WorkflowVersion


class WorkflowDefinitionError(ApplicationError):
    """Raised when a workflow definition fails schema or contract validation."""


@dataclass(frozen=True)
class ParsedWorkflowDefinition:
    workflow: WorkflowCreate
    workflow_version: WorkflowVersionCreate


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def workflow_spec_root() -> Path:
    return repo_root() / "packages" / "workflow-spec"


def workflow_schema_path() -> Path:
    return workflow_spec_root() / "schema" / "workflow.schema.json"


def canonical_support_ticket_workflow_path() -> Path:
    return workflow_spec_root() / "examples" / "support-ticket-resolution.v1.yaml"


def load_workflow_schema() -> dict[str, Any]:
    return json.loads(workflow_schema_path().read_text())


def load_workflow_definition_file(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise WorkflowDefinitionError("workflow definition file must contain a top-level mapping")
    return loaded


def validate_workflow_definition(document: dict[str, Any]) -> None:
    try:
        Draft202012Validator(load_workflow_schema()).validate(document)
    except JSONSchemaValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        prefix = f"{path}: " if path else ""
        raise WorkflowDefinitionError(f"{prefix}{exc.message}") from exc

    workflow = document["workflow"]
    for field_name in ("input_schema", "output_schema"):
        try:
            Draft202012Validator.check_schema(workflow[field_name])
        except Exception as exc:  # jsonschema raises SchemaError here
            raise WorkflowDefinitionError(f"{field_name} is not a valid JSON Schema: {exc}") from exc

    try:
        parse_workflow_definition(document)
    except PydanticValidationError as exc:
        raise WorkflowDefinitionError(str(exc)) from exc


def parse_workflow_definition(
    document: dict[str, Any],
    *,
    created_by: UUID | None = None,
) -> ParsedWorkflowDefinition:
    workflow = document["workflow"]
    workflow_create = WorkflowCreate(
        slug=workflow["slug"],
        name=workflow["name"],
        domain=workflow["domain"],
        description=workflow["description"],
    )
    workflow_version = WorkflowVersionCreate(
        version=workflow["version"],
        prompt_template=workflow["prompt_template"],
        input_schema=workflow["input_schema"],
        output_schema=workflow["output_schema"],
        model_config=workflow["model"],
        policy_pack=workflow.get("policies", []),
        tool_set=workflow.get("tools", []),
        guardrails=workflow.get("guardrails", []),
        rollout_config=workflow.get("rollout"),
        eval_dataset_bindings=workflow.get("eval_dataset_bindings", []),
        created_by=created_by,
    )
    return ParsedWorkflowDefinition(workflow=workflow_create, workflow_version=workflow_version)


def build_workflow_definition_document(workflow: Workflow, workflow_version: WorkflowVersion) -> dict[str, Any]:
    workflow_document: dict[str, Any] = {
        "name": workflow.name,
        "slug": workflow.slug,
        "domain": workflow.domain,
        "version": workflow_version.version,
        "description": workflow.description or workflow.name,
        "prompt_template": workflow_version.prompt_template,
        "input_schema": workflow_version.input_schema_json,
        "output_schema": workflow_version.output_schema_json,
        "model": {key: value for key, value in workflow_version.model_config_json.items() if value is not None},
        "tools": workflow_version.tool_set_json,
        "policies": workflow_version.policy_pack_json,
        "guardrails": workflow_version.guardrails_json,
        "eval_dataset_bindings": workflow_version.eval_dataset_bindings_json,
    }
    if workflow_version.rollout_config_json is not None:
        workflow_document["rollout"] = workflow_version.rollout_config_json
    return {"workflow": workflow_document}
