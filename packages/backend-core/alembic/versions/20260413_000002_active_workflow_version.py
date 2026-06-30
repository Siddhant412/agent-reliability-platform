"""Add active workflow version pointer."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_000002"
down_revision = "20260413_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.add_column(sa.Column("active_version_id", sa.Uuid(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_workflows_active_version_id_workflow_versions",
            "workflow_versions",
            ["active_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.drop_constraint("fk_workflows_active_version_id_workflow_versions", type_="foreignkey")
        batch_op.drop_column("active_version_id")
