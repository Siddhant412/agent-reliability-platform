# `apps/worker`

Deterministic local worker for workflow execution, approval pause/resume,
offline evals, and rollout monitoring. This package is also the future Temporal
worker boundary.

Worker implementations load pinned workflow versions from persistence and call
shared domain, policy, and tool gateway interfaces from `packages/backend-core`.

Current implementation:

- `arp_worker.runner.execute_run` executes one queued or resumed run
  deterministically.
- `arp_worker.runner.execute_next_queued_run` picks the oldest queued run,
  optionally within a project.
- `arp_worker.evals.execute_next_queued_eval_run` picks the oldest queued eval
  run and executes its dataset.
- `arp_worker.queue.process_work_queue` processes queued runs and eval runs in
  one local queue loop.
- `arp-worker-run --project-id <uuid> [--run-id <uuid>]` runs a specific run.
- `arp-worker-run --project-id <uuid> --eval-run-id <uuid>` runs a specific
  eval run.
- `arp-worker-run --project-id <uuid> --queue-kind all --max-items 10` drains
  queued work once.
- `arp-worker-run --project-id <uuid> --queue-kind all --poll` keeps polling
  for queued work.

This is intentionally not a Temporal worker yet. It validates the persistence
contract first: `queued -> running -> succeeded/failed`, approval pause/resume,
trace span writes, and deterministic structured output.

The deterministic worker calls the support-demo tools, persists each call in
`tool_calls`, creates approval requests for policy-gated mutating actions, and
validates final output against the pinned workflow version schema.

Tool execution goes through `arp_core.tools.gateway.ToolGateway`. The default
local adapter uses support-demo tools, and future MCP/external adapters should
implement the same gateway boundary.
