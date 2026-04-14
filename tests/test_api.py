from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def _workflow_version_payload() -> dict:
    return {
        "version": "1.0.0",
        "prompt_template": "Resolve support tickets safely.",
        "input_schema": {
            "type": "object",
            "required": ["ticket_id", "customer_id", "message"],
            "properties": {
                "ticket_id": {"type": "string"},
                "customer_id": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["summary", "disposition", "confidence"],
            "properties": {
                "summary": {"type": "string"},
                "disposition": {"type": "string"},
                "confidence": {"type": "number"},
            },
        },
        "model_config": {
            "provider": "openai",
            "name": "gpt-5",
            "temperature": 0.2,
        },
        "tool_set": [
            {"name": "kb_search"},
            {"name": "get_customer_profile"},
            {"name": "issue_refund"},
        ],
        "policy_pack": [
            {
                "name": "refund_approval",
                "when": "tool.name == 'issue_refund' and tool.args.amount > 100",
                "action": "require_approval",
                "approver_role": "supervisor",
            }
        ],
        "guardrails": [
            "sanitize_tool_inputs",
            "redact_secrets_from_traces",
            "enforce_output_schema",
        ],
        "rollout_config": {
            "strategy": "canary",
            "baseline_version": "1.0.0",
            "candidate_version": "1.1.0",
            "traffic_split": {"baseline": 90, "candidate": 10},
            "rollback_thresholds": {
                "policy_violation_rate": 0,
                "schema_failure_rate": 0.01,
                "p95_latency_ms": 30000,
            },
        },
    }


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_publish_and_submit_version_pinned_run(client: TestClient) -> None:
    headers = {"X-Actor-User-Id": str(uuid4())}

    org_response = client.post(
        "/api/v1/organizations",
        json={"name": "Acme Corp", "slug": "acme-corp"},
        headers=headers,
    )
    assert org_response.status_code == 201
    org_id = org_response.json()["id"]

    project_response = client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": "Support Ops", "slug": "support-ops", "environment": "staging"},
        headers=headers,
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    workflow_response = client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={
            "slug": "support-ticket-resolution",
            "name": "Support Ticket Resolution",
            "domain": "customer_support",
            "description": "Resolve billing and order issues safely.",
        },
        headers=headers,
    )
    assert workflow_response.status_code == 201
    workflow_id = workflow_response.json()["id"]

    version_response = client.post(
        f"/api/v1/workflows/{workflow_id}/versions",
        json=_workflow_version_payload(),
        headers=headers,
    )
    assert version_response.status_code == 201
    version_body = version_response.json()
    version_id = version_body["id"]
    assert version_body["status"] == "draft"
    assert "model_config" in version_body
    assert "model_config_payload" not in version_body

    draft_run_response = client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={
            "workflow_version_id": version_id,
            "input_payload": {
                "ticket_id": "T-100",
                "customer_id": "C-200",
                "message": "I was double charged.",
                "priority": "high",
            },
        },
        headers=headers,
    )
    assert draft_run_response.status_code == 409
    assert draft_run_response.json()["detail"] == "runs can only be created from published workflow versions"

    publish_response = client.post(
        f"/api/v1/workflow-versions/{version_id}/publish",
        json={"published_by": str(uuid4())},
        headers=headers,
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"

    run_response = client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={
            "workflow_version_id": version_id,
            "input_payload": {
                "ticket_id": "T-100",
                "customer_id": "C-200",
                "message": "I was double charged.",
                "priority": "high",
            },
        },
        headers=headers,
    )
    assert run_response.status_code == 201
    run_body = run_response.json()
    assert run_body["workflow_version_id"] == version_id
    assert run_body["status"] == "queued"
    assert run_body["input_payload"]["ticket_id"] == "T-100"

    get_run_response = client.get(f"/api/v1/projects/{project_id}/runs/{run_body['id']}")
    assert get_run_response.status_code == 200
    assert get_run_response.json()["id"] == run_body["id"]

