## Logical architecture

```text
Browser / API clients
  |
  | HTTPS + tenant auth context
  v
Next.js Web Console
  |
  | typed HTTP API
  v
FastAPI Control Plane
  |\
  | \--> Postgres
  | \--> Redis
  | \--> MinIO / S3
  | \--> OpenTelemetry exporter
  |
  v
Temporal Cluster
  |
  v
Temporal Worker Service
  |\
  | \--> Agent Runtime (OpenAI Agents SDK adapter)
  | \--> Tool Gateway (MCP + local support tools)
  | \--> Policy Engine
  | \--> Trace Writer
  | \--> Eval Runner
  |
  v
Model providers + MCP servers + enterprise systems
```

## Service responsibilities

### Next.js Web Console (`apps/web`)

- Workflow builder and version browser.
- Run and trace viewer.
- Approval inbox.
- Eval dashboard and rollout controls.
- Admin pages for projects, members, connectors, and audit logs.

The UI should not embed domain rules. It renders backend state and calls typed
APIs with tenant/project context.

### FastAPI Control Plane (`apps/api`)

- AuthN/AuthZ and tenant context extraction.
- CRUD APIs for organizations, projects, memberships, connectors, workflows,
  workflow versions, datasets, eval runs, rollouts, and approvals.
- Run submission APIs that resolve rollout routing, create the `Run` row, pin
  the workflow version, and start a Temporal workflow.
- Trace/query APIs optimized for run timelines and filtering.
- Audit logging for all governance-sensitive mutations.

The API owns request validation and persistence transactions. It should not
perform long-running agent execution inline.

### Temporal Worker Service (`apps/worker`)

- Executes support-ticket workflows and future workflow domains.
- Implements durable pause/resume around approval requests.
- Runs dataset-based offline eval batches.
- Applies canary/shadow rollout routing decisions provided by the control
  plane and writes execution outcomes.

Temporal workflows coordinate state transitions; activities call adapters for
models, tools, policy checks, and persistence.

### Shared Backend Core (`packages/backend-core`)

This package holds framework-independent Python domain/application code shared
by API and worker:

- Domain models and value objects for workflow versions, runs, traces,
  approvals, datasets, evals, and rollout decisions.
- Repository interfaces and SQLAlchemy implementations.
- Pydantic request/response schemas and workflow DSL parser contracts.
- Policy engine, redaction helpers, audit event builder, and trace writer.
- Tool gateway interfaces and local demo tool adapters.

FastAPI routes and Temporal activities should stay thin and call this package.

### Workflow Spec Package (`packages/workflow-spec`)

- Canonical YAML/JSON schema for workflow definitions.
- Example DSL files for the support-ticket workflow.
- Parser/validation contract and golden fixtures.

This package is the boundary that keeps workflow version authoring explicit and
testable instead of hard-coding prompt/tool/policy config in runtime code.

### Support Demo Package (`packages/support-demo`)

- Deterministic support-domain fixtures and seed data.
- Realistic local tool stubs for `kb_search`, `get_customer_profile`,
  `get_order`, `issue_refund`, `post_ticket_comment`, and
  `send_customer_email`.
- Demo MCP adapter contracts that mimic external tool metadata and auth scopes.

## Control-plane and data-plane split

- Control plane: FastAPI + Postgres handle tenancy, CRUD, audit, routing
  decisions, and run submission.
- Data plane: Temporal workers execute agent workflows, emit traces, invoke
  policy checks, and call tools.
- Shared state boundary: all durable state transitions are persisted in
  Postgres; Redis is only for cache/coordination and never the source of truth.

## Core runtime flows

### 1) Run submission and version pinning

1. Client submits a support-ticket payload to a workflow slug.
2. API resolves organization/project scope from auth context.
3. API selects the active workflow version through rollout rules.
4. API inserts `runs` with `workflow_version_id`, input payload, and `queued`
   status in the same transaction that writes an audit event.
5. API starts a Temporal workflow with `run_id` and the pinned version ID.
6. Worker loads the immutable workflow version and executes the agent.

### 2) Policy-gated tool execution

1. Agent proposes a tool call.
2. Tool gateway records a `tool.proposed` span and calls the policy engine.
3. Policy engine evaluates the tool metadata, tool args, run input, workflow
   policy pack, tenant/project context, and caller role.
4. Read-only allowed calls execute immediately.
5. Mutating or risky calls either execute, get denied, or create an approval
   request.
6. Secrets and sensitive args are redacted before traces or audit payloads are
   stored.

### 3) Approval pause/resume

1. Policy returns `require_approval` for a proposed tool call.
2. Worker stores `tool_calls` and `approval_requests`, emits
   `approval.wait`, marks the run `awaiting_approval`, and blocks on a Temporal
   signal.
3. Approver reviews the request in the UI and submits approve/reject with a
   decision note.
4. API writes the approval decision and audit event, then signals the Temporal
   workflow.
5. Worker resumes the run, emits `approval.decision`, and either executes the
   approved call or routes the rejection back into the agent context.

### 4) Trace persistence and retrieval

- Worker emits OpenTelemetry spans for `run.start`, `agent.step`,
  `model.call`, `tool.proposed`, `tool.execute`, `guardrail.check`,
  `approval.wait`, `approval.decision`, `output.validate`, and `run.finish`.
- A trace writer persists normalized span rows in Postgres for product queries
  and UI timelines.
- OTLP export to an observability backend remains enabled for platform
  operations, but the product trace viewer reads from Postgres so traces are
  queryable by tenant/project/workflow version.

### 5) Offline evals and regression comparison

1. Builder selects a dataset version, candidate workflow version, and baseline
   workflow version.
2. API creates an `eval_runs` record and starts a Temporal eval workflow.
3. Worker replays each `eval_case` against the pinned candidate version.
4. Graders compute schema validity, action correctness, policy violations,
   rubric scores, latency, and cost.
5. Worker stores per-case results and aggregate summaries, then compares
   candidate metrics against baseline.
6. Failing examples can be promoted into datasets with links to original runs
   and trace spans.

### 6) Canary rollout

- Rollout configs live on workflow versions and a workflow-level active rollout
  selector.
- API routes each new run to baseline or candidate deterministically using a
  stable hash of `(project_id, workflow_slug, ticket_id/request_id)`.
- The chosen version is persisted on the run row before execution, which keeps
  traces and evals reproducible.
- A rollout monitor compares canary and baseline metrics and can flip the
  workflow back to baseline when thresholds breach.

## Domain model boundaries

The first implementation should keep these aggregate boundaries explicit:

- Tenant governance: `Organization`, `Project`, `Membership`, `AuditEvent`.
- Tooling: `Connector`, `ToolDefinition`.
- Workflow registry: `Workflow`, `WorkflowVersion`.
- Execution: `Run`, `TraceSpan`, `ToolCall`, `ApprovalRequest`.
- Evaluation: `Dataset`, `EvalCase`, `EvalRun`, `EvalCaseResult`.
- Rollout: `WorkflowRollout` or rollout fields on a workflow pointer plus
  immutable rollout config stored on workflow versions.

Cross-aggregate writes should happen in application services with explicit
transactions; avoid implicit ORM side effects across modules.

## Tenancy and authorization model

- Every API request resolves an authenticated principal and an active
  organization/project scope.
- Repository methods require tenant identifiers as arguments and must include
  those IDs in queries.
- Background workers receive `run_id`, `project_id`, and `workflow_version_id`
  and re-load tenant context from Postgres before touching data.
- Role checks are centralized in an authorization service with explicit actions
  such as `workflow.publish`, `run.read`, `approval.decide`, and
  `connector.manage`.
- Audit events store actor, tenant, action, resource type/id, and before/after
  payload hashes or redacted snapshots.

## Reliability and consistency rules

- Postgres is the system of record for workflow versions, run state, approvals,
  traces, evals, and audit logs.
- Temporal owns long-running orchestration and approval waits; API handlers
  should remain short-lived.
- External tool/model failures are converted into typed run events and
  retriable Temporal activity failures when safe.
- Mutating external actions need idempotency keys derived from `run_id` and
  `tool_call_id`.
- Run state transitions should be guarded by explicit state-machine checks so
  `awaiting_approval -> resumed -> succeeded/failed` remains auditable.
- Workflow version rows are immutable after publish; drafts may be edited, but
  published versions are append-only.

## Observability and trace storage

- Use OpenTelemetry instrumentation in API and worker services with a shared
  trace context format.
- Store product-facing trace spans in Postgres with tenant/project/run/version
  columns for filtered queries.
- Export OTLP to a collector for infra-level observability.
- Record token usage, latency, cost, selected model, selected tools, policy
  decisions, retries, and sanitized error payloads.
- Never persist plaintext secrets or raw connector credentials in span
  attributes, logs, or audit event payloads.

## V1 support-ticket workflow boundary

The first vertical slice should implement one workflow:

- Input: `ticket_id`, `customer_id`, `message`, `priority`.
- Read tools: `kb_search`, `get_customer_profile`, `get_order`.
- Mutating tools: `issue_refund`, `post_ticket_comment`, `send_customer_email`.
- Approval policy: refund amount > 100 requires supervisor approval; high
  priority customer email requires team lead approval.
- Output: structured case summary, disposition, proposed/executed actions,
  customer reply draft, confidence score.
