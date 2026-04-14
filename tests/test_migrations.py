from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_core_tables(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'alembic-smoke.db'}"
    monkeypatch.setenv("ARP_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert {
        "organizations",
        "projects",
        "workflows",
        "workflow_versions",
        "runs",
        "trace_spans",
        "approval_requests",
        "datasets",
        "eval_runs",
        "audit_events",
    }.issubset(tables)

    engine.dispose()

