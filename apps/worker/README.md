# `apps/worker`

Temporal worker service for workflow execution, approval pause/resume, offline
evals, and rollout monitoring.

Workflow and activity implementations should load pinned workflow versions from
Postgres and call shared domain/policy/tool interfaces from
`packages/backend-core`.

Current implementation:

- `arp_worker.runner.execute_run` executes one queued or resumed run
  deterministically.
- `arp_worker.runner.execute_next_queued_run` picks the oldest queued run,
  optionally within a project.
- `arp-worker-run --project-id <uuid> [--run-id <uuid>]` runs the local worker
  against `ARP_DATABASE_URL` or `.arp/dev.db`.

This is intentionally not a Temporal worker yet. It validates the persistence
contract first: `queued -> running -> succeeded/failed`, approval pause/resume,
trace span writes, and deterministic structured output.

The deterministic worker calls the support-demo tools, persists each call in
`tool_calls`, creates approval requests for policy-gated mutating actions, and
validates final output against the pinned workflow version schema.
