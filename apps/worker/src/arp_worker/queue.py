from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from arp_worker.evals import execute_next_queued_eval_run
from arp_worker.runner import execute_next_queued_run


@dataclass(frozen=True)
class QueueItemResult:
    work_type: str
    project_id: UUID
    resource_id: UUID
    status: str


def process_next_work_item(
    session: Session,
    *,
    project_id: UUID | None = None,
    queue_kind: str = "all",
    claim_ttl_seconds: int = 300,
    max_attempts: int = 3,
) -> QueueItemResult | None:
    if queue_kind not in {"all", "run", "eval"}:
        raise ValueError("queue_kind must be one of: all, run, eval")

    if queue_kind in {"all", "run"}:
        run_result = execute_next_queued_run(
            session,
            project_id=project_id,
            claim_ttl_seconds=claim_ttl_seconds,
            max_attempts=max_attempts,
        )
        if run_result is not None:
            return QueueItemResult(
                work_type="run",
                project_id=run_result.project_id,
                resource_id=run_result.run_id,
                status=run_result.status.value,
            )

    if queue_kind in {"all", "eval"}:
        eval_result = execute_next_queued_eval_run(
            session,
            project_id=project_id,
            claim_ttl_seconds=claim_ttl_seconds,
        )
        if eval_result is not None:
            return QueueItemResult(
                work_type="eval_run",
                project_id=eval_result.project_id,
                resource_id=eval_result.eval_run_id,
                status=eval_result.status.value,
            )

    return None


def process_work_queue(
    session: Session,
    *,
    project_id: UUID | None = None,
    queue_kind: str = "all",
    max_items: int = 1,
    claim_ttl_seconds: int = 300,
    max_attempts: int = 3,
) -> list[QueueItemResult]:
    results: list[QueueItemResult] = []
    for _ in range(max_items):
        result = process_next_work_item(
            session,
            project_id=project_id,
            queue_kind=queue_kind,
            claim_ttl_seconds=claim_ttl_seconds,
            max_attempts=max_attempts,
        )
        if result is None:
            break
        results.append(result)
    return results
