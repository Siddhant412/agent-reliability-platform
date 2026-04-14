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


def _headers() -> dict[str, str]:
    return {"X-Actor-User-Id": str(uuid4())}


def _create_org(client: TestClient, *, actor_headers: dict[str, str], slug: str = "acme-corp") -> str:
    response = client.post(
        "/api/v1/organizations",
        json={"name": "Acme Corp", "slug": slug},
        headers=actor_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_project(client: TestClient, *, org_id: str, actor_headers: dict[str, str], slug: str = "support-ops") -> str:
    response = client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": "Support Ops", "slug": slug, "environment": "staging"},
        headers=actor_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_workflow(client: TestClient, *, project_id: str, actor_headers: dict[str, str]) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={
            "slug": "support-ticket-resolution",
            "name": "Support Ticket Resolution",
            "domain": "customer_support",
            "description": "Resolve billing and order issues safely.",
        },
        headers=actor_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_and_publish_workflow_version(
    client: TestClient,
    *,
    workflow_id: str,
    actor_headers: dict[str, str],
) -> str:
    version_response = client.post(
        f"/api/v1/workflows/{workflow_id}/versions",
        json=_workflow_version_payload(),
        headers=actor_headers,
    )
    assert version_response.status_code == 201
    version_body = version_response.json()
    assert version_body["status"] == "draft"
    assert "model_config" in version_body
    assert "model_config_payload" not in version_body

    version_id = version_body["id"]
    publish_response = client.post(
        f"/api/v1/workflow-versions/{version_id}/publish",
        json={"published_by": str(uuid4())},
        headers=actor_headers,
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    return version_id


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_secured_routes_require_actor_identity_header(client: TestClient) -> None:
    response = client.get("/api/v1/organizations")

    assert response.status_code == 401
    assert response.json()["detail"] == "missing X-Actor-User-Id header"


def test_org_creator_is_bootstrapped_as_admin_and_org_list_is_tenant_filtered(client: TestClient) -> None:
    actor_one = _headers()
    actor_two = _headers()

    org_one = _create_org(client, actor_headers=actor_one, slug="acme-corp")
    org_two = _create_org(client, actor_headers=actor_two, slug="beta-corp")

    me_response = client.get("/api/v1/auth/me", headers=actor_one)
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["user_id"] == actor_one["X-Actor-User-Id"]
    assert len(me_body["memberships"]) == 1
    assert me_body["memberships"][0]["org_id"] == org_one
    assert me_body["memberships"][0]["role"] == "org_admin"

    actor_one_orgs = client.get("/api/v1/organizations", headers=actor_one)
    assert actor_one_orgs.status_code == 200
    assert [record["id"] for record in actor_one_orgs.json()] == [org_one]

    actor_two_orgs = client.get("/api/v1/organizations", headers=actor_two)
    assert actor_two_orgs.status_code == 200
    assert [record["id"] for record in actor_two_orgs.json()] == [org_two]


def test_project_membership_controls_workflow_and_run_access(client: TestClient) -> None:
    owner = _headers()
    api_client_actor = _headers()
    outsider = _headers()

    org_id = _create_org(client, actor_headers=owner)
    project_id = _create_project(client, org_id=org_id, actor_headers=owner)
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
    )

    forbidden_before_membership = client.get(f"/api/v1/projects/{project_id}/runs", headers=outsider)
    assert forbidden_before_membership.status_code == 403

    membership_response = client.post(
        f"/api/v1/projects/{project_id}/memberships",
        json={"user_id": api_client_actor["X-Actor-User-Id"], "role": "api_client"},
        headers=owner,
    )
    assert membership_response.status_code == 201
    assert membership_response.json()["role"] == "api_client"

    forbidden_workflow_write = client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={
            "slug": "unauthorized-workflow",
            "name": "Unauthorized Workflow",
            "domain": "customer_support",
        },
        headers=api_client_actor,
    )
    assert forbidden_workflow_write.status_code == 403

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
        headers=api_client_actor,
    )
    assert run_response.status_code == 201
    run_body = run_response.json()
    assert run_body["workflow_version_id"] == version_id
    assert run_body["status"] == "queued"

    get_run_response = client.get(
        f"/api/v1/projects/{project_id}/runs/{run_body['id']}",
        headers=api_client_actor,
    )
    assert get_run_response.status_code == 200
    assert get_run_response.json()["id"] == run_body["id"]

    outsider_run_response = client.post(
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
        headers=outsider,
    )
    assert outsider_run_response.status_code == 403

    project_memberships = client.get(f"/api/v1/projects/{project_id}/memberships", headers=owner)
    assert project_memberships.status_code == 200
    assert {record["user_id"] for record in project_memberships.json()} == {
        owner["X-Actor-User-Id"],
        api_client_actor["X-Actor-User-Id"],
    }
