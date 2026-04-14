## Tree

```text
.
|-- README.md
|-- agent_reliability_platform_spec.md
|-- apps/
|   |-- api/
|   |   |-- README.md
|   |   `-- src/
|   |-- worker/
|   |   |-- README.md
|   |   `-- src/
|   `-- web/
|       |-- README.md
|       `-- src/
|-- packages/
|   |-- backend-core/
|   |   |-- README.md
|   |   `-- src/
|   |-- support-demo/
|   |   |-- README.md
|   |   `-- src/
|   `-- workflow-spec/
|       |-- README.md
|       |-- examples/
|       `-- schema/
|-- infra/
|   |-- docker/
|   |   `-- README.md
|   `-- otel/
|       `-- README.md
|-- docs/
|   `-- architecture/
|       |-- monorepo-plan.md
|       `-- system-architecture.md
`-- scripts/
    `-- README.md
```

## Package responsibilities

### `apps/api`

FastAPI service for the control plane.

Planned modules:

- `src/arp_api/main.py` - app factory, middleware, health routes.
- `src/arp_api/routes/` - thin HTTP route modules grouped by domain.
- `src/arp_api/dependencies/` - auth, tenant scope, DB session, Temporal client.
- `src/arp_api/openapi/` - generated OpenAPI artifacts for frontend client use.

Rules:

- Route handlers should delegate business logic to `packages/backend-core`.
- Every request touching project data must depend on an explicit tenant/project
  scope object.
- Never start long-running agent work inline; enqueue Temporal workflows.

### `apps/worker`

Temporal worker process for runtime, approvals, evals, and rollout monitors.

Planned modules:

- `src/arp_worker/main.py` - worker bootstrap.
- `src/arp_worker/workflows/` - Temporal workflow definitions.
- `src/arp_worker/activities/` - activity adapters for model calls, tools,
  policy checks, persistence, and grading.

Rules:

- Temporal workflows own orchestration and durable waits.
- Activities should call shared interfaces from `packages/backend-core`.
- Worker payloads must carry run/version IDs, not mutable prompt/tool config
  blobs, so execution always reloads the pinned version.

### `apps/web`

Next.js dashboard for workflow authoring, runs, traces, approvals, evals, and
rollouts.

Planned modules:

- `src/app/` - route segments and server components.
- `src/features/` - domain-oriented UI modules.
- `src/lib/api/` - generated or hand-written typed API client.
- `src/lib/auth/` - session handling and project scope selection.

Rules:

- UI state should mirror backend resource IDs and versions.
- Workflow editing screens can manipulate drafts, but publish actions should
  make immutability explicit in the UI.
- Trace and approval screens must show sanitized payloads only.

### `packages/backend-core`

Shared Python package containing business logic and infrastructure adapters
used by both API and worker services.

Planned modules:

- `src/arp_core/domain/` - domain entities, enums, value objects, state
  transitions.
- `src/arp_core/application/` - use cases such as create workflow version,
  submit run, decide approval, execute tool call, start eval run, update
  rollout.
- `src/arp_core/contracts/` - Pydantic DTOs and workflow DSL models.
- `src/arp_core/persistence/` - SQLAlchemy models, Alembic migrations,
  repository implementations, transaction helpers.
- `src/arp_core/policy/` - policy rule evaluation, redaction, approval
  decisions.
- `src/arp_core/tracing/` - span/event persistence and query services.
- `src/arp_core/tools/` - tool gateway interfaces, registry metadata, MCP/local
  adapters.
- `src/arp_core/evals/` - dataset execution and grading interfaces.
- `src/arp_core/rollouts/` - routing and threshold evaluation.

Rules:

- Domain/application code should not depend on FastAPI route objects or
  Temporal decorators.
- Repositories must require tenant scope in method signatures for
  tenant-scoped reads/writes.
- Published workflow versions are immutable at the domain layer.

### `packages/workflow-spec`

Workflow DSL schema and fixtures.

Planned contents:

- `schema/workflow.schema.json` - JSON Schema for workflow YAML/JSON documents.
- `examples/support-ticket-resolution.v1.yaml` - canonical demo workflow.
- `README.md` - versioning rules and parser contract.

Rules:

- The DSL schema should be strict enough to reject unknown top-level keys and
  malformed policy/tool definitions.
- The parser should produce canonical typed config stored on
  `workflow_versions`.

### `packages/support-demo`

Customer support demo dataset and deterministic local tool stubs.

Planned modules:

- Demo customer/order/ticket fixtures.
- Seed scripts for local Postgres.
- Local implementations of support tools with realistic success/failure paths
  and idempotency behavior.

Rules:

- Demo tools must respect mutating/read-only metadata so policy checks stay
  realistic.
- Seed data should be reproducible and tenant-scoped.

### `infra/docker`

Docker Compose and service config for local development:

- Postgres
- Redis
- Temporal
- MinIO
- OpenTelemetry collector / Jaeger
- API, worker, and web containers once app code exists

### `infra/otel`

Collector configuration, trace attribute conventions, and local observability
defaults.

### `scripts`

Developer automation for codegen, migrations, seed data, and local bootstrap.

## API and contract strategy

- Python Pydantic models in `packages/backend-core` are the source for FastAPI
  OpenAPI generation.
- Frontend API types should be generated from the backend OpenAPI schema once
  route contracts stabilize.
- Workflow DSL documents are validated against `packages/workflow-spec/schema`
  before they become `WorkflowVersion` rows.
- Temporal workflow payload contracts should use explicit Pydantic models and
  stable schema versions.

## Database and migration strategy

- Put SQLAlchemy models and Alembic migrations in `packages/backend-core` so
  API and worker services share one persistence layer.
- Use Postgres enums or constrained text for run/tool/approval/workflow states,
  but keep corresponding Python enums in domain code.
- Add tenant IDs and supporting indexes to all project-scoped tables.
- Persist immutable workflow version payloads as structured JSON columns plus
  normalized relational references for queryable fields.
- Store trace spans as append-only rows keyed by `(project_id, run_id,
  trace_id, span_id)`.

## Testing plan

- `packages/backend-core`: unit tests for domain state transitions, policy
  decisions, rollout routing, and repository integration tests against Postgres.
- `apps/api`: route tests for auth/tenancy boundaries, validation errors, and
  use-case wiring.
- `apps/worker`: Temporal workflow tests for run success, approval pause/resume,
  retries, and failure recording.
- `packages/workflow-spec`: schema validation tests and golden fixtures.
- `packages/support-demo`: deterministic tool contract tests.
- `apps/web`: component tests for run/approval/trace views plus Playwright smoke
  tests once APIs exist.
