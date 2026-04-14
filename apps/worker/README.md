# `apps/worker`

Temporal worker service for workflow execution, approval pause/resume, offline
evals, and rollout monitoring.

Workflow and activity implementations should load pinned workflow versions from
Postgres and call shared domain/policy/tool interfaces from
`packages/backend-core`.
