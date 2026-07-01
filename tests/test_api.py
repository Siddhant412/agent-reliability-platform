from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def _workflow_version_payload(*, version: str = "1.0.0") -> dict:
    return {
        "version": version,
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
    version: str = "1.0.0",
) -> str:
    version_response = client.post(
        f"/api/v1/workflows/{workflow_id}/versions",
        json=_workflow_version_payload(version=version),
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

    invalid_run_response = client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={
            "workflow_version_id": version_id,
            "input_payload": {
                "ticket_id": "T-101",
                "customer_id": "C-201",
            },
        },
        headers=api_client_actor,
    )
    assert invalid_run_response.status_code == 400
    assert invalid_run_response.json()["detail"] == "input_payload: 'message' is a required property"

    runs_response = client.get(f"/api/v1/projects/{project_id}/runs", headers=api_client_actor)
    assert runs_response.status_code == 200
    assert [record["id"] for record in runs_response.json()] == [run_body["id"]]

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


def test_workflow_slug_run_submission_resolves_latest_published_version(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="slug-run-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="slug-run-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    first_version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
        version="1.0.0",
    )

    draft_response = client.post(
        f"/api/v1/workflows/{workflow_id}/versions",
        json=_workflow_version_payload(version="1.1.0"),
        headers=owner,
    )
    assert draft_response.status_code == 201
    draft_version_id = draft_response.json()["id"]

    run_while_candidate_is_draft = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-200",
                "customer_id": "C-300",
                "message": "Where is my order?",
            },
        },
        headers=owner,
    )
    assert run_while_candidate_is_draft.status_code == 201
    assert run_while_candidate_is_draft.json()["workflow_version_id"] == first_version_id

    publish_candidate_response = client.post(
        f"/api/v1/workflow-versions/{draft_version_id}/publish",
        json={"published_by": owner["X-Actor-User-Id"]},
        headers=owner,
    )
    assert publish_candidate_response.status_code == 200

    run_after_candidate_publish = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-201",
                "customer_id": "C-301",
                "message": "I need a refund.",
            },
        },
        headers=owner,
    )
    assert run_after_candidate_publish.status_code == 201
    assert run_after_candidate_publish.json()["workflow_version_id"] == draft_version_id

    invalid_payload_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-202",
                "customer_id": "C-302",
            },
        },
        headers=owner,
    )
    assert invalid_payload_response.status_code == 400
    assert invalid_payload_response.json()["detail"] == "input_payload: 'message' is a required property"

    unknown_slug_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/missing-workflow/runs",
        json={
            "input_payload": {
                "ticket_id": "T-203",
                "customer_id": "C-303",
                "message": "This workflow does not exist.",
            },
        },
        headers=owner,
    )
    assert unknown_slug_response.status_code == 404
    assert unknown_slug_response.json()["detail"] == "workflow not found"


def test_workflow_slug_submission_uses_active_version_when_set(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="active-version-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="active-version-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    first_version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
        version="1.0.0",
    )
    second_version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
        version="1.1.0",
    )

    active_response = client.post(
        f"/api/v1/workflows/{workflow_id}/active-version",
        json={"workflow_version_id": first_version_id},
        headers=owner,
    )
    assert active_response.status_code == 200
    assert active_response.json()["active_version_id"] == first_version_id

    run_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-250",
                "customer_id": "C-250",
                "message": "Use active version.",
            },
        },
        headers=owner,
    )
    assert run_response.status_code == 201
    assert run_response.json()["workflow_version_id"] == first_version_id
    assert run_response.json()["workflow_version_id"] != second_version_id


def test_canary_rollout_activation_routes_slug_runs_to_candidate(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="rollout-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="rollout-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    baseline_version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
        version="1.0.0",
    )

    candidate_payload = _workflow_version_payload(version="1.1.0")
    candidate_payload["rollout_config"] = {
        "strategy": "canary",
        "baseline_version": "1.0.0",
        "candidate_version": "1.1.0",
        "traffic_split": {"baseline": 0, "candidate": 100},
        "rollback_thresholds": {"schema_failure_rate": 0.01},
    }
    candidate_response = client.post(
        f"/api/v1/workflows/{workflow_id}/versions",
        json=candidate_payload,
        headers=owner,
    )
    assert candidate_response.status_code == 201
    candidate_version_id = candidate_response.json()["id"]
    publish_candidate_response = client.post(
        f"/api/v1/workflow-versions/{candidate_version_id}/publish",
        json={"published_by": owner["X-Actor-User-Id"]},
        headers=owner,
    )
    assert publish_candidate_response.status_code == 200

    activate_response = client.post(
        f"/api/v1/workflows/{workflow_id}/rollout/activate",
        json={"candidate_version_id": candidate_version_id},
        headers=owner,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["active_version_id"] == candidate_version_id

    run_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-ROLL-1",
                "customer_id": "C-200",
                "message": "Where is my order?",
            },
        },
        headers=owner,
    )
    assert run_response.status_code == 201
    assert run_response.json()["workflow_version_id"] == candidate_version_id
    assert run_response.json()["workflow_version_id"] != baseline_version_id


def test_support_demo_connector_seed_and_tool_registry(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="connector-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="connector-ops")

    empty_connectors = client.get(f"/api/v1/projects/{project_id}/connectors", headers=owner)
    assert empty_connectors.status_code == 200
    assert empty_connectors.json() == []

    seed_response = client.post(f"/api/v1/projects/{project_id}/connectors/support-demo/seed", headers=owner)
    assert seed_response.status_code == 200
    seeded_tools = seed_response.json()
    assert {tool["name"] for tool in seeded_tools} == {
        "kb_search",
        "get_customer_profile",
        "get_order",
        "issue_refund",
        "post_ticket_comment",
        "send_customer_email",
    }
    assert next(tool for tool in seeded_tools if tool["name"] == "issue_refund")["is_mutating"] is True

    connectors_response = client.get(f"/api/v1/projects/{project_id}/connectors", headers=owner)
    assert connectors_response.status_code == 200
    connectors = connectors_response.json()
    assert len(connectors) == 1
    connector = connectors[0]
    assert connector["name"] == "Support Demo"
    assert connector["status"] == "active"

    tools_response = client.get(
        f"/api/v1/projects/{project_id}/connectors/{connector['id']}/tools",
        headers=owner,
    )
    assert tools_response.status_code == 200
    assert [tool["name"] for tool in tools_response.json()] == sorted(tool["name"] for tool in seeded_tools)


def test_run_status_transitions_and_trace_span_writes(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="trace-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="trace-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
    )

    run_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-300",
                "customer_id": "C-400",
                "message": "I was charged twice.",
            },
        },
        headers=owner,
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    invalid_terminal_response = client.patch(
        f"/api/v1/projects/{project_id}/runs/{run_id}/status",
        json={"status": "succeeded", "final_output": {"summary": "too early"}},
        headers=owner,
    )
    assert invalid_terminal_response.status_code == 409
    assert invalid_terminal_response.json()["detail"] == "invalid run status transition: queued -> succeeded"

    running_response = client.patch(
        f"/api/v1/projects/{project_id}/runs/{run_id}/status",
        json={"status": "running"},
        headers=owner,
    )
    assert running_response.status_code == 200
    running_body = running_response.json()
    assert running_body["status"] == "running"
    assert running_body["started_at"] is not None

    span_payload = {
        "trace_id": "0" * 32,
        "span_id": "1" * 16,
        "span_type": "run.start",
        "name": "run.start",
        "status": "in_progress",
        "attributes": {"workflow_slug": "support-ticket-resolution"},
    }
    span_response = client.post(
        f"/api/v1/projects/{project_id}/runs/{run_id}/trace-spans",
        json=span_payload,
        headers=owner,
    )
    assert span_response.status_code == 201
    span_body = span_response.json()
    assert span_body["workflow_version_id"] == version_id
    assert span_body["attributes"] == {"workflow_slug": "support-ticket-resolution"}

    duplicate_span_response = client.post(
        f"/api/v1/projects/{project_id}/runs/{run_id}/trace-spans",
        json=span_payload,
        headers=owner,
    )
    assert duplicate_span_response.status_code == 409
    assert duplicate_span_response.json()["detail"] == "trace span already exists"

    spans_response = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}/trace-spans", headers=owner)
    assert spans_response.status_code == 200
    assert [record["span_id"] for record in spans_response.json()] == ["1" * 16]

    filtered_spans_response = client.get(
        f"/api/v1/projects/{project_id}/runs/{run_id}/trace-spans",
        params={"span_type": "run.start", "status": "in_progress"},
        headers=owner,
    )
    assert filtered_spans_response.status_code == 200
    assert [record["span_id"] for record in filtered_spans_response.json()] == ["1" * 16]

    timeline_response = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}/timeline", headers=owner)
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert timeline["run"]["id"] == run_id
    assert [record["span_id"] for record in timeline["trace_spans"]] == ["1" * 16]
    assert timeline["tool_calls"] == []
    assert timeline["approvals"] == []

    tool_calls_response = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}/tool-calls", headers=owner)
    assert tool_calls_response.status_code == 200
    assert tool_calls_response.json() == []

    succeeded_response = client.patch(
        f"/api/v1/projects/{project_id}/runs/{run_id}/status",
        json={
            "status": "succeeded",
            "final_output": {"summary": "Resolved duplicate charge.", "confidence": 0.93},
            "tokens_input": 120,
            "tokens_output": 64,
        },
        headers=owner,
    )
    assert succeeded_response.status_code == 200
    succeeded_body = succeeded_response.json()
    assert succeeded_body["status"] == "succeeded"
    assert succeeded_body["ended_at"] is not None
    assert succeeded_body["final_output"] == {"summary": "Resolved duplicate charge.", "confidence": 0.93}
    assert succeeded_body["tokens_input"] == 120
    assert succeeded_body["tokens_output"] == 64

    rerun_response = client.patch(
        f"/api/v1/projects/{project_id}/runs/{run_id}/status",
        json={"status": "running"},
        headers=owner,
    )
    assert rerun_response.status_code == 409
    assert rerun_response.json()["detail"] == "invalid run status transition: succeeded -> running"


def test_approval_routes_allow_required_approver_to_decide(client: TestClient) -> None:
    owner = _headers()
    supervisor = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="approval-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="approval-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
    )
    membership_response = client.post(
        f"/api/v1/projects/{project_id}/memberships",
        json={"user_id": supervisor["X-Actor-User-Id"], "role": "supervisor"},
        headers=owner,
    )
    assert membership_response.status_code == 201

    run_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-500",
                "customer_id": "C-500",
                "message": "I was charged twice and need a refund.",
            },
        },
        headers=owner,
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    execute_response = client.post(f"/api/v1/projects/{project_id}/runs/{run_id}/execute", headers=owner)
    assert execute_response.status_code == 200
    assert execute_response.json()["status"] == "awaiting_approval"

    approvals_response = client.get(
        f"/api/v1/projects/{project_id}/approvals",
        params={"status": "pending"},
        headers=owner,
    )
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval["approver_role"] == "supervisor"
    assert approval["proposed_effect"]["tool_name"] == "issue_refund"

    decided_response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{approval['id']}/decide",
        json={"status": "approved", "decision_note": "Duplicate charge confirmed."},
        headers=supervisor,
    )
    assert decided_response.status_code == 200
    decided = decided_response.json()
    assert decided["status"] == "approved"
    assert decided["decided_by"] == supervisor["X-Actor-User-Id"]

    run_after_decision = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}", headers=owner)
    assert run_after_decision.status_code == 200
    assert run_after_decision.json()["status"] == "resumed"

    resumed_response = client.post(f"/api/v1/projects/{project_id}/runs/{run_id}/execute", headers=owner)
    assert resumed_response.status_code == 200
    resumed_body = resumed_response.json()
    assert resumed_body["status"] == "succeeded"
    assert resumed_body["final_output"]["disposition"] == "resolved"

    tool_calls_response = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}/tool-calls", headers=owner)
    assert tool_calls_response.status_code == 200
    refund_call = next(record for record in tool_calls_response.json() if record["tool_name"] == "issue_refund")
    assert refund_call["status"] == "executed"
    assert refund_call["result"]["status"] == "issued"


def test_execute_endpoint_completes_rejected_approval_as_escalated(client: TestClient) -> None:
    owner = _headers()
    supervisor = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="approval-reject-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="approval-reject-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
    )
    membership_response = client.post(
        f"/api/v1/projects/{project_id}/memberships",
        json={"user_id": supervisor["X-Actor-User-Id"], "role": "supervisor"},
        headers=owner,
    )
    assert membership_response.status_code == 201

    run_response = client.post(
        f"/api/v1/projects/{project_id}/workflows/support-ticket-resolution/runs",
        json={
            "input_payload": {
                "ticket_id": "T-501",
                "customer_id": "C-500",
                "message": "I was charged twice and need a refund.",
            },
        },
        headers=owner,
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    execute_response = client.post(f"/api/v1/projects/{project_id}/runs/{run_id}/execute", headers=owner)
    assert execute_response.status_code == 200
    assert execute_response.json()["status"] == "awaiting_approval"

    approvals_response = client.get(
        f"/api/v1/projects/{project_id}/approvals",
        params={"status": "pending"},
        headers=owner,
    )
    assert approvals_response.status_code == 200
    approval = approvals_response.json()[0]

    rejected_response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{approval['id']}/decide",
        json={"status": "rejected", "decision_note": "Refund not supported by payment evidence."},
        headers=supervisor,
    )
    assert rejected_response.status_code == 200
    assert rejected_response.json()["status"] == "rejected"

    resumed_response = client.post(f"/api/v1/projects/{project_id}/runs/{run_id}/execute", headers=owner)
    assert resumed_response.status_code == 200
    resumed_body = resumed_response.json()
    assert resumed_body["status"] == "succeeded"
    assert resumed_body["final_output"]["disposition"] == "escalated"
    assert resumed_body["final_output"]["proposed_actions"] == [
        {
            "tool": "manual_review",
            "reason": "A requested action was rejected and needs a safer follow-up.",
        }
    ]

    tool_calls_response = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}/tool-calls", headers=owner)
    assert tool_calls_response.status_code == 200
    refund_call = next(record for record in tool_calls_response.json() if record["tool_name"] == "issue_refund")
    assert refund_call["status"] == "rejected"
    assert refund_call["result"] is None


def test_eval_run_executes_dataset_and_records_case_results(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="eval-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="eval-ops")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)
    baseline_version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
        version="1.0.0",
    )
    candidate_version_id = _create_and_publish_workflow_version(
        client,
        workflow_id=workflow_id,
        actor_headers=owner,
        version="1.1.0",
    )

    dataset_response = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "support-smoke", "version": "1.0.0", "description": "Core support evals."},
        headers=owner,
    )
    assert dataset_response.status_code == 201
    dataset_id = dataset_response.json()["id"]

    valid_case_response = client.post(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/cases",
        json={
            "input_payload": {
                "ticket_id": "E-100",
                "customer_id": "C-200",
                "message": "Where is my order?",
            },
            "expected": {"disposition": "resolved"},
            "tags": ["smoke", "order"],
        },
        headers=owner,
    )
    assert valid_case_response.status_code == 201

    invalid_case_response = client.post(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/cases",
        json={
            "input_payload": {
                "ticket_id": "E-101",
                "customer_id": "C-201",
            },
            "expected": {"disposition": "invalid"},
            "tags": ["schema"],
        },
        headers=owner,
    )
    assert invalid_case_response.status_code == 201

    create_eval_response = client.post(
        f"/api/v1/projects/{project_id}/eval-runs",
        json={
            "dataset_id": dataset_id,
            "workflow_version_id": candidate_version_id,
            "baseline_version_id": baseline_version_id,
        },
        headers=owner,
    )
    assert create_eval_response.status_code == 201
    eval_run_id = create_eval_response.json()["id"]

    execute_response = client.post(f"/api/v1/projects/{project_id}/eval-runs/{eval_run_id}/execute", headers=owner)
    assert execute_response.status_code == 200
    executed = execute_response.json()
    assert executed["status"] == "succeeded"
    assert executed["summary"]["total_cases"] == 2
    assert executed["summary"]["succeeded"] == 1
    assert executed["summary"]["failed"] == 1
    assert executed["summary"]["schema_valid"] == 1
    assert executed["summary"]["success_rate"] == 0.5
    assert executed["summary"]["baseline_succeeded"] == 1
    assert executed["summary"]["baseline_failed"] == 1
    assert executed["summary"]["baseline_success_rate"] == 0.5
    assert executed["summary"]["unchanged"] == 2

    results_response = client.get(f"/api/v1/projects/{project_id}/eval-runs/{eval_run_id}/results", headers=owner)
    assert results_response.status_code == 200
    results = results_response.json()
    assert len(results) == 2
    assert {record["status"] for record in results} == {"succeeded", "failed"}
    succeeded_result = next(record for record in results if record["status"] == "succeeded")
    assert succeeded_result["run_id"] is not None
    assert succeeded_result["scores"]["baseline"]["run_succeeded"] is True
    assert succeeded_result["scores"]["comparison"] == "unchanged"
    failed_result = next(record for record in results if record["status"] == "failed" and record["run_id"] is None)
    assert "message" in failed_result["error"]


def test_draft_versions_can_be_updated_but_only_valid_definitions_can_publish(client: TestClient) -> None:
    owner = _headers()

    org_id = _create_org(client, actor_headers=owner, slug="gamma-corp")
    project_id = _create_project(client, org_id=org_id, actor_headers=owner, slug="ops-gamma")
    workflow_id = _create_workflow(client, project_id=project_id, actor_headers=owner)

    invalid_payload = _workflow_version_payload()
    invalid_payload["version"] = "2.0.0"
    invalid_payload["input_schema"] = {"type": "not-a-real-json-schema-type"}

    version_response = client.post(
        f"/api/v1/workflows/{workflow_id}/versions",
        json=invalid_payload,
        headers=owner,
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]

    get_draft_response = client.get(f"/api/v1/workflow-versions/{version_id}", headers=owner)
    assert get_draft_response.status_code == 200
    assert get_draft_response.json()["version"] == "2.0.0"

    invalid_publish_response = client.post(
        f"/api/v1/workflow-versions/{version_id}/publish",
        json={"published_by": owner["X-Actor-User-Id"]},
        headers=owner,
    )
    assert invalid_publish_response.status_code == 400
    assert "input_schema is not a valid JSON Schema" in invalid_publish_response.json()["detail"]

    patch_response = client.patch(
        f"/api/v1/workflow-versions/{version_id}",
        json={
            "version": "2.0.1",
            "input_schema": {
                "type": "object",
                "required": ["ticket_id", "customer_id", "message"],
                "properties": {
                    "ticket_id": {"type": "string"},
                    "customer_id": {"type": "string"},
                    "message": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
            "tool_set": ["kb_search", "get_customer_profile", "issue_refund"],
        },
        headers=owner,
    )
    assert patch_response.status_code == 200
    patched_body = patch_response.json()
    assert patched_body["version"] == "2.0.1"
    assert [tool["name"] for tool in patched_body["tool_set"]] == [
        "kb_search",
        "get_customer_profile",
        "issue_refund",
    ]

    publish_response = client.post(
        f"/api/v1/workflow-versions/{version_id}/publish",
        json={"published_by": owner["X-Actor-User-Id"]},
        headers=owner,
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"

    update_published_response = client.patch(
        f"/api/v1/workflow-versions/{version_id}",
        json={"prompt_template": "Do not allow this edit."},
        headers=owner,
    )
    assert update_published_response.status_code == 409
    assert update_published_response.json()["detail"] == "only draft workflow versions can be updated"
