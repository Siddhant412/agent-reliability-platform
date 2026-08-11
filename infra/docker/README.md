# `infra/docker`

This directory provides the runnable local container stack for the current
MVP: PostgreSQL, FastAPI, the deterministic queue worker, the Next.js console,
and an OpenTelemetry Collector. Redis, Temporal, MinIO, MCP services, and a
model provider are not included because the checked-in application does not
use them yet.

## Start the stack

Run these commands from the repository root. The compose build context must be
the repository root because the Python image installs the shared packages.

```bash
docker compose \
  --env-file infra/docker/.env.example \
  -f infra/docker/docker-compose.yml \
  up --build -d
```

Wait until the API is healthy, then seed the disposable demo workspace:

```bash
docker compose \
  --env-file infra/docker/.env.example \
  -f infra/docker/docker-compose.yml \
  --profile bootstrap run --rm bootstrap
```

Open the console at `http://localhost:3000` and the API docs at
`http://localhost:8000/docs`. The web service proxies browser API requests to
the `api` service inside the Compose network through `ARP_API_BASE_URL`.

The API and worker use `ARP_DATABASE_URL`; Compose supplies a PostgreSQL URL
that points at the `postgres` service. The API runs Alembic migrations before
it starts, and the worker waits for API health so it does not poll before the
schema exists. Both services export OTLP telemetry to the local collector; use
`docker compose ... logs otel-collector` to inspect its debug output. The
polling worker restarts automatically after a transient database restart.

## Local configuration

[`.env.example`](.env.example) contains local-only defaults for database
credentials and host ports. Copy it to an untracked file and pass that file to
`--env-file` when changing values. The default password is deliberately
insecure and must not be reused outside an isolated local machine. PostgreSQL
uses host port `5433` by default to avoid a local PostgreSQL service on `5432`;
containers continue to use the internal `postgres:5432` address.

`postgres-data` is a named Docker volume. To reset the demo database, stop the
stack and remove that specific volume:

```bash
docker compose \
  --env-file infra/docker/.env.example \
  -f infra/docker/docker-compose.yml \
  down --volumes
```

This removes all Compose-managed local database data. Recreate the stack and
run the bootstrap command afterward.

## Images

- `Dockerfile.python` installs the root Python project and is shared by API,
  worker, and bootstrap services.
- `Dockerfile.web` builds the existing locked Next.js application and runs it
  with `next start`.
- The Dockerfile-specific ignore files keep unrelated local state and web build
  output out of their build contexts.

No host source directory is mounted into containers. Edit source locally and
rebuild the affected service to test changes.

## PostgreSQL queue tests

The PostgreSQL queue integration tests create and remove a randomly named
schema, leaving other schemas untouched. Run them against a disposable
database from the Compose network (not a potentially conflicting host port):

```bash
docker run --rm \
  --network agent-reliability-platform_default \
  -v "$PWD:/workspace:ro" -w /workspace \
  -e ARP_TEST_POSTGRES_URL=postgresql+psycopg://arp:arp-local-only@postgres:5432/arp \
  agent-reliability-platform-api \
  sh -c 'uv pip install --python /app/.venv/bin/python pytest httpx && /app/.venv/bin/pytest -m postgres'
```
