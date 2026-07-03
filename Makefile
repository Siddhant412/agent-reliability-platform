.PHONY: bootstrap dev-api dev-web worker test web-build openapi

bootstrap:
	uv sync --dev
	uv run python scripts/bootstrap_demo.py

dev-api:
	uv run uvicorn arp_api.main:app --reload

dev-web:
	cd apps/web && npm install && npm run dev

worker:
	uv run arp-worker-run --queue-kind all --max-items 10

test:
	uv run pytest

web-build:
	cd apps/web && npm run build

openapi:
	uv run python scripts/export_openapi.py
