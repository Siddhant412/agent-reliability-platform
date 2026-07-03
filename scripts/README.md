# `scripts`

Developer automation for local bootstrap, migrations, code generation, seed
data, and smoke tests.

Available scripts:

- `uv run python scripts/bootstrap_demo.py` creates or updates the local demo
  org, project, support workflow, active version, support-demo connector/tools,
  and smoke eval dataset.
- `uv run python scripts/export_openapi.py` writes the FastAPI OpenAPI schema
  and frontend TypeScript API types.
- `uv run python scripts/seed_support_workflow.py` is the older workflow-only
  seed path; prefer `bootstrap_demo.py` for current local development.
