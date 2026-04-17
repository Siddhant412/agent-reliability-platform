from __future__ import annotations

import argparse
import os
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from arp_core.application import services
from arp_core.contracts.tenant import OrganizationCreate, ProjectCreate
from arp_core.contracts.workflow import PublishWorkflowVersionRequest
from arp_core.persistence.models import Organization, Project, Workflow, WorkflowVersion
from arp_core.persistence.session import SessionManager
from arp_core.workflow_registry.validation import (
    canonical_support_ticket_workflow_path,
    load_workflow_definition_file,
    parse_workflow_definition,
    validate_workflow_definition,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the canonical support-ticket workflow.")
    parser.add_argument("--database-url", default=os.getenv("ARP_DATABASE_URL", "sqlite+pysqlite:///./.arp/dev.db"))
    parser.add_argument("--org-name", default="Demo Org")
    parser.add_argument("--org-slug", default="demo-org")
    parser.add_argument("--project-name", default="Support Ops")
    parser.add_argument("--project-slug", default="support-ops")
    parser.add_argument(
        "--actor-user-id",
        default=os.getenv("ARP_SEED_ACTOR_USER_ID", "00000000-0000-0000-0000-000000000001"),
    )
    parser.add_argument("--publish", action="store_true", default=True)
    parser.add_argument("--no-publish", dest="publish", action="store_false")
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

        if args.publish and workflow_version.status.value == "draft":
            workflow_version = services.publish_workflow_version(
                session,
                workflow_version_id=workflow_version.id,
                payload=PublishWorkflowVersionRequest(published_by=actor_user_id),
                actor_user_id=actor_user_id,
            )

        session.commit()

        org_slug = organization.slug
        project_slug = project.slug
        workflow_slug = workflow.slug
        version_value = workflow_version.version
        status_value = workflow_version.status.value

    print(f"organization={org_slug}")
    print(f"project={project_slug}")
    print(f"workflow={workflow_slug}")
    print(f"workflow_version={version_value}")
    print(f"status={status_value}")


if __name__ == "__main__":
    main()
