"""Add worker execution claims and durable tool idempotency keys."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260805_000003"
down_revision = "20260413_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("claim_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_unique_constraint("uq_runs_claim_token", ["claim_token"])
    with op.batch_alter_table("eval_runs") as batch_op:
        batch_op.add_column(sa.Column("claim_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_unique_constraint("uq_eval_runs_claim_token", ["claim_token"])
    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=200), nullable=True))
        batch_op.create_unique_constraint("uq_tool_calls_project_idempotency_key", ["project_id", "idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.drop_constraint("uq_tool_calls_project_idempotency_key", type_="unique")
        batch_op.drop_column("idempotency_key")
    with op.batch_alter_table("eval_runs") as batch_op:
        batch_op.drop_constraint("uq_eval_runs_claim_token", type_="unique")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("claim_expires_at")
        batch_op.drop_column("claimed_at")
        batch_op.drop_column("claim_token")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_constraint("uq_runs_claim_token", type_="unique")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("claim_expires_at")
        batch_op.drop_column("claimed_at")
        batch_op.drop_column("claim_token")
