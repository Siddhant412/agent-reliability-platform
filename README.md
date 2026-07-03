# Agent Reliability Platform

Multi-tenant control plane for reliable enterprise agent workflows. The current
implementation is a local deterministic MVP for support operations: workflow
versions, policy-gated tool calls, approvals, traces, evals, canary routing,
audit events, and a queue-processing worker.

## Current Stack

- Web console: Next.js + TypeScript
- API: FastAPI + Pydantic + SQLAlchemy
- Persistence: SQLite by default via `ARP_DATABASE_URL`, Postgres-compatible
  models and migrations
- Worker: deterministic local Python worker with queued run and eval processing
- Demo tools: local support fixtures and deterministic tool stubs

## Implemented Surface

- Tenant bootstrap with organizations, projects, memberships, and role checks
- Workflow registry with draft/published versions and active version selection
- Support-ticket run submission by workflow slug with pinned version IDs
- Trace spans, tool calls, approval requests, and approval decisions
- Dataset and eval-run APIs with candidate/baseline comparison summaries
- Canary rollout activation and deterministic baseline/candidate routing
- Project-scoped audit event API and dashboard panel
- Local worker queue for queued runs and queued eval runs
- Demo bootstrap for a complete local support-ops workspace

## Repository Layout

```text
apps/
  api/      FastAPI control plane
  worker/   deterministic local worker and queue processor
  web/      Next.js dashboard
packages/
  backend-core/   shared domain, contracts, persistence, policies, services
  workflow-spec/  workflow DSL schema and support-ticket example
  support-demo/   local support fixtures and deterministic tools
infra/
  docker/   planned local service config
  otel/     planned collector config
docs/
  architecture/
scripts/
  bootstrap_demo.py
  export_openapi.py
```

## Local Demo

From the repository root:

```bash
uv sync --dev
uv run python scripts/bootstrap_demo.py
uv run uvicorn arp_api.main:app --reload
```

In another shell:

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`, keep the default actor ID, and paste the
`project_id` printed by `scripts/bootstrap_demo.py`.

## Useful Commands

```bash
make bootstrap
make dev-api
make dev-web
make worker
make test
make web-build
make openapi
```

Equivalent direct commands:

```bash
uv run pytest
uv run arp-worker-run --queue-kind all --max-items 10
uv run arp-worker-run --queue-kind all --poll
uv run python scripts/export_openapi.py
```

Use `X-Actor-User-Id: <uuid>` when calling secured API routes directly.
