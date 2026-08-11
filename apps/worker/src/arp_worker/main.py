from __future__ import annotations

import argparse
import os
import time
from uuid import UUID

from arp_core.persistence.session import SessionManager
from arp_core.observability import configure_telemetry
from arp_worker.evals import execute_eval_run
from arp_worker.queue import process_work_queue
from arp_worker.runner import execute_next_queued_run, execute_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute queued ARP runs with the deterministic local worker.")
    parser.add_argument("--database-url", default=os.getenv("ARP_DATABASE_URL", "sqlite+pysqlite:///./.arp/dev.db"))
    parser.add_argument("--project-id", type=UUID)
    parser.add_argument("--run-id", type=UUID)
    parser.add_argument("--eval-run-id", type=UUID)
    parser.add_argument("--queue-kind", choices=["all", "run", "eval"], default="all")
    parser.add_argument("--max-items", type=int, default=1)
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--claim-ttl-seconds", type=int, default=300)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--otel-endpoint", default=os.getenv("ARP_OTEL_ENDPOINT"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_items < 1:
        raise SystemExit("--max-items must be at least 1")
    if args.claim_ttl_seconds < 1:
        raise SystemExit("--claim-ttl-seconds must be at least 1")
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts must be at least 1")
    if args.run_id is not None and args.eval_run_id is not None:
        raise SystemExit("--run-id and --eval-run-id are mutually exclusive")
    if (args.run_id is not None or args.eval_run_id is not None) and args.project_id is None:
        raise SystemExit("--project-id is required when executing a specific run or eval run")

    manager = SessionManager(args.database_url)
    configure_telemetry(service_name="arp-worker", endpoint=args.otel_endpoint)
    if args.run_id is not None:
        with manager.session() as session:
            result = execute_run(session, project_id=args.project_id, run_id=args.run_id)
            session.commit()
        print(f"project_id={result.project_id}")
        print(f"run_id={result.run_id}")
        print(f"workflow_version_id={result.workflow_version_id}")
        print(f"status={result.status.value}")
        print(f"trace_id={result.trace_id}")
        return 0

    if args.eval_run_id is not None:
        with manager.session() as session:
            result = execute_eval_run(session, project_id=args.project_id, eval_run_id=args.eval_run_id)
            session.commit()
        print(f"project_id={result.project_id}")
        print(f"eval_run_id={result.eval_run_id}")
        print(f"status={result.status.value}")
        return 0

    while True:
        with manager.session() as session:
            if args.queue_kind == "run" and args.max_items == 1:
                run_result = execute_next_queued_run(
                    session,
                    project_id=args.project_id,
                    claim_ttl_seconds=args.claim_ttl_seconds,
                    max_attempts=args.max_attempts,
                )
                results = []
                if run_result is not None:
                    results.append(
                        {
                            "work_type": "run",
                            "project_id": run_result.project_id,
                            "resource_id": run_result.run_id,
                            "status": run_result.status.value,
                        }
                    )
            else:
                results = [
                    {
                        "work_type": item.work_type,
                        "project_id": item.project_id,
                        "resource_id": item.resource_id,
                        "status": item.status,
                    }
                    for item in process_work_queue(
                        session,
                        project_id=args.project_id,
                        queue_kind=args.queue_kind,
                        max_items=args.max_items,
                        claim_ttl_seconds=args.claim_ttl_seconds,
                        max_attempts=args.max_attempts,
                    )
                ]
            session.commit()

        if not results:
            print("status=idle")
            if not args.poll:
                return 0
            time.sleep(args.poll_interval)
            continue

        for item in results:
            print(
                " ".join(
                    [
                        f"work_type={item['work_type']}",
                        f"project_id={item['project_id']}",
                        f"resource_id={item['resource_id']}",
                        f"status={item['status']}",
                    ]
                )
            )
        if not args.poll:
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
