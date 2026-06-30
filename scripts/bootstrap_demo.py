from __future__ import annotations

import argparse
import os
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from arp_core.application import services
from arp_core.contracts.eval import DatasetCreate, EvalCaseCreate
from arp_core.contracts.tenant import OrganizationCreate, ProjectCreate
from arp_core.contracts.tooling import ConnectorCreate, ToolDefinitionCreate
from arp_core.contracts.workflow import PublishWorkflowVersionRequest, SetActiveWorkflowVersionRequest
from arp_core.domain.enums import ConnectorAuthMode, ConnectorStatus, ConnectorType, ToolRiskLevel
from arp_core.persistence.models import Dataset, Organization, Project, Workflow, WorkflowVersion
from arp_core.persistence.session import SessionManager
from arp_core.workflow_registry.validation import (
    canonical_support_ticket_workflow_path,
    load_workflow_definition_file,
    parse_workflow_definition,
    validate_workflow_definition,
)
from arp_support_demo.tools import TOOL_METADATA


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a local ARP demo workspace.")
    parser.add_argument("--database-url", default=os.getenv("ARP_DATABASE_URL", "sqlite+pysqlite:///./.arp/dev.db"))
    parser.add_argument("--org-name", default="Demo Org")
    parser.add_argument("--org-slug", default="demo-org")
    parser.add_argument("--project-name", default="Support Ops")
    parser.add_argument("--project-slug", default="support-ops")
    parser.add_argument(
        "--actor-user-id",
        default=os.getenv("ARP_SEED_ACTOR_USER_ID", "00000000-0000-0000-0000-000000000001"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    actor_user_id = UUID(args.actor_user_id)
    os.environ["ARP_DATABASE_URL"] = args.database_url
    command.upgrade(Config("alembic.ini"), "head")

    document = load_workflow_definition_file(canonical_support_ticket_workflow_path())
    validate_workflow_definition(document)
    parsed = parse_workflow_definition(document, created_by=actor_user_id)

    manager = SessionManager(args.database_url)
    with manager.session() as session:
        organization = session.scalar(select(Organization).where(Organization.slug == args.org_slug))
        if organization is None:
            organization = services.create_organization(
                session,
                payload=OrganizationCreate(name=args.org_name, slug=args.org_slug),
                actor_user_id=actor_user_id,
            )

        project = session.scalar(
            select(Project).where(Project.org_id == organization.id, Project.slug == args.project_slug)
        )
        if project is None:
            project = services.create_project(
                session,
                org_id=organization.id,
                payload=ProjectCreate(name=args.project_name, slug=args.project_slug, environment="staging"),
                actor_user_id=actor_user_id,
            )

        workflow = session.scalar(
            select(Workflow).where(Workflow.project_id == project.id, Workflow.slug == parsed.workflow.slug)
        )
        if workflow is None:
            workflow = services.create_workflow(
                session,
                project_id=project.id,
                payload=parsed.workflow,
                actor_user_id=actor_user_id,
            )

        workflow_version = session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version == parsed.workflow_version.version,
            )
        )
        if workflow_version is None:
            workflow_version = services.create_workflow_version(
                session,
                workflow_id=workflow.id,
                payload=parsed.workflow_version,
                actor_user_id=actor_user_id,
            )
        if workflow_version.status.value == "draft":
            workflow_version = services.publish_workflow_version(
                session,
                workflow_version_id=workflow_version.id,
                payload=PublishWorkflowVersionRequest(published_by=actor_user_id),
                actor_user_id=actor_user_id,
            )
        if workflow.active_version_id != workflow_version.id:
            workflow = services.set_active_workflow_version(
                session,
                workflow_id=workflow.id,
                payload=SetActiveWorkflowVersionRequest(workflow_version_id=workflow_version.id),
                actor_user_id=actor_user_id,
            )

        connector = next(
            (record for record in services.list_connectors(session, project_id=project.id) if record.name == "Support Demo"),
            None,
        )
        if connector is None:
            connector = services.create_connector(
                session,
                project_id=project.id,
                payload=ConnectorCreate(
                    name="Support Demo",
                    connector_type=ConnectorType.LOCAL,
                    auth_mode=ConnectorAuthMode.NONE,
                    scopes=["support:read", "support:write"],
                    status=ConnectorStatus.ACTIVE,
                ),
                actor_user_id=actor_user_id,
            )

        existing_tools = {
            tool.name: tool
            for tool in services.list_tool_definitions(session, project_id=project.id, connector_id=connector.id)
        }
        for metadata in TOOL_METADATA.values():
            if metadata.name in existing_tools:
                continue
            services.create_tool_definition(
                session,
                project_id=project.id,
                connector_id=connector.id,
                payload=ToolDefinitionCreate(
                    name=metadata.name,
                    description=metadata.description,
                    risk_level=ToolRiskLevel(metadata.risk_level),
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    is_mutating=metadata.is_mutating,
                ),
                actor_user_id=actor_user_id,
            )

        dataset = session.scalar(
            select(Dataset).where(
                Dataset.project_id == project.id,
                Dataset.name == "support-smoke",
                Dataset.version == "1.0.0",
            )
        )
        if dataset is None:
            dataset = services.create_dataset(
                session,
                project_id=project.id,
                payload=DatasetCreate(
                    name="support-smoke",
                    version="1.0.0",
                    description="Small deterministic support eval dataset.",
                ),
                actor_user_id=actor_user_id,
            )
        if not services.list_eval_cases(session, project_id=project.id, dataset_id=dataset.id):
            for eval_case in _demo_eval_cases():
                services.create_eval_case(
                    session,
                    project_id=project.id,
                    dataset_id=dataset.id,
                    payload=eval_case,
                )

        session.commit()

        print(f"actor_user_id={actor_user_id}")
        print(f"organization_id={organization.id}")
        print(f"project_id={project.id}")
        print(f"workflow_id={workflow.id}")
        print(f"workflow_slug={workflow.slug}")
        print(f"workflow_version_id={workflow_version.id}")
        print(f"dataset_id={dataset.id}")
        print(f"connector_id={connector.id}")


def _demo_eval_cases() -> list[EvalCaseCreate]:
    return [
        EvalCaseCreate(
            input_payload={
                "ticket_id": "EVAL-100",
                "customer_id": "C-200",
                "message": "Where is my order?",
                "priority": "medium",
            },
            expected={"disposition": "resolved"},
            tags=["order", "read-tools"],
        ),
        EvalCaseCreate(
            input_payload={
                "ticket_id": "EVAL-200",
                "customer_id": "C-500",
                "message": "I was charged twice and need a refund.",
                "priority": "high",
            },
            expected={"requires_approval": True},
            tags=["billing", "approval"],
        ),
    ]


if __name__ == "__main__":
    main()
