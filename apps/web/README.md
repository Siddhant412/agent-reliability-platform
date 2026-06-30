# `apps/web`

Next.js console for workflow authoring, run inspection, approval review, eval
dashboards, rollout management, and tenant administration.

The UI should consume typed backend APIs and never rely on unsanitized trace or
secret payloads.

## Local demo

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
