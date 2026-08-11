from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from arp_core.domain.enums import RunStatus
from arp_core.persistence.base import Base, utcnow
from arp_core.persistence.models import Run
from arp_core.persistence.session import SessionManager
from arp_worker.runner import _claim_next_queued_run, execute_next_queued_run
from tests.test_worker import _create_queued_run


@pytest.fixture
def postgres_manager() -> Iterator[SessionManager]:
    """Provide the explicitly configured disposable PostgreSQL test database."""
    database_url = os.getenv("ARP_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("set ARP_TEST_POSTGRES_URL to run PostgreSQL queue integration tests")

    schema = f"arp_test_{uuid4().hex}"
    bootstrap_manager = SessionManager(database_url)
    with bootstrap_manager.engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    separator = "&" if "?" in database_url else "?"
    manager = SessionManager(f"{database_url}{separator}options=-csearch_path%3D{schema}")
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        Base.metadata.drop_all(manager.engine)
        manager.engine.dispose()
        with bootstrap_manager.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        bootstrap_manager.engine.dispose()


@pytest.mark.postgres
def test_postgres_skip_locked_allows_only_one_worker_claim(postgres_manager: SessionManager) -> None:
    with postgres_manager.session() as seed_session:
        project, _, run = _create_queued_run(seed_session)
        project_id = project.id
        run_id = run.id
        seed_session.commit()

    with postgres_manager.session() as first_worker:
        claimed = _claim_next_queued_run(first_worker, project_id=project_id)
        assert claimed is not None
        assert claimed[0].id == run_id

        with postgres_manager.session() as second_worker:
            assert _claim_next_queued_run(second_worker, project_id=project_id) is None
            second_worker.rollback()

        first_worker.rollback()


@pytest.mark.postgres
def test_postgres_reclaims_expired_run_and_completes_it(postgres_manager: SessionManager) -> None:
    with postgres_manager.session() as seed_session:
        project, _, run = _create_queued_run(seed_session)
        project_id = project.id
        run_id = run.id
        run.status = RunStatus.RUNNING
        run.claim_token = "expired-claim"
        run.claimed_at = utcnow() - timedelta(minutes=10)
        run.claim_expires_at = utcnow() - timedelta(minutes=5)
        seed_session.commit()

    with postgres_manager.session() as worker_session:
        result = execute_next_queued_run(worker_session, project_id=project_id)
        worker_session.commit()

    assert result is not None
    assert result.run_id == run_id
    assert result.status == RunStatus.SUCCEEDED

    with postgres_manager.session() as verification_session:
        persisted_run = verification_session.get(Run, run_id)
        assert persisted_run is not None
        assert persisted_run.status == RunStatus.SUCCEEDED
        assert persisted_run.attempt_count == 1
        assert persisted_run.claim_token is None
        assert persisted_run.claim_expires_at is None
