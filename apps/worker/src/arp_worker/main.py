from __future__ import annotations

import argparse
import os
from uuid import UUID

from arp_core.persistence.session import SessionManager
from arp_worker.runner import execute_next_queued_run, execute_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute queued ARP runs with the deterministic local worker.")
    parser.add_argument("--database-url", default=os.getenv("ARP_DATABASE_URL", "sqlite+pysqlite:///./.arp/dev.db"))
    parser.add_argument("--project-id", type=UUID, required=True)
    parser.add_argument("--run-id", type=UUID)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manager = SessionManager(args.database_url)
    with manager.session() as session:
        if args.run_id is None:
            result = execute_next_queued_run(session, project_id=args.project_id)
        else:
            result = execute_run(session, project_id=args.project_id, run_id=args.run_id)
        session.commit()

    if result is None:
        print("status=idle")
        return 0

    print(f"project_id={result.project_id}")
    print(f"run_id={result.run_id}")
    print(f"workflow_version_id={result.workflow_version_id}")
    print(f"status={result.status.value}")
    print(f"trace_id={result.trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

