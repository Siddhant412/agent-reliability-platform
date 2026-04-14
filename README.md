# Agent Reliability Platform for Enterprise Workflows

Multi-tenant AI workflow control plane for support operations, focused on
versioned execution, policy-gated tool use, traceability, evals, and safe
rollouts.

## Stack

- Frontend: Next.js + TypeScript
- Backend API: FastAPI + Pydantic + SQLAlchemy
- Workflow orchestration: Temporal
- Agent runtime: OpenAI Agents SDK
- Database/cache/storage: Postgres, Redis, MinIO/S3
- Observability: OpenTelemetry

## Repository layout

```text
apps/
  api/      FastAPI control plane
  worker/   Temporal workers and agent runtime
  web/      Next.js dashboard
packages/
  backend-core/   Shared Python domain, policies, persistence, and contracts
  workflow-spec/  Workflow DSL schemas, examples, and parser contract
  support-demo/   Customer-support demo fixtures and deterministic tool stubs
infra/
  docker/   Local Docker Compose and service config
  otel/     OpenTelemetry collector config
docs/
  architecture/
```

## Backend quickstart

```bash
uv sync --dev
uv run alembic -c alembic.ini upgrade head
uv run uvicorn arp_api.main:app --reload
```
