from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from arp_core.application import services
from arp_core.application.exceptions import ConflictError
from arp_core.contracts.run import WorkflowRunSubmitRequest
from arp_core.contracts.tenant import OrganizationCreate, ProjectCreate
from arp_core.contracts.workflow import PublishWorkflowVersionRequest, WorkflowCreate, WorkflowVersionCreate
from arp_core.domain.enums import ApprovalStatus, MembershipRole, RunStatus, SpanStatus, ToolCallStatus
from arp_worker.runner import execute_next_queued_run, execute_run


def _workflow_version_payload() -> WorkflowVersionCreate:
    return WorkflowVersionCreate.model_validate(
        {
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
                "required": ["summary", "disposition", "proposed_actions", "customer_reply", "confidence"],
                "properties": {
                    "summary": {"type": "string"},
                    "disposition": {"type": "string"},
                    "proposed_actions": {"type": "array"},
                    "customer_reply": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
            "model_config": {"provider": "openai", "name": "gpt-5", "temperature": 0.2},
            "tool_set": ["kb_search", "post_ticket_comment"],
            "policy_pack": [],
            "guardrails": ["enforce_output_schema"],
        }
    )


def _approval_workflow_version_payload() -> WorkflowVersionCreate:
    payload = _workflow_version_payload().model_dump(mode="json", by_alias=True)
    payload["tool_set"] = [
        "kb_search",
        "get_customer_profile",
        "get_order",
        "issue_refund",
        "post_ticket_comment",
    ]
    payload["policy_pack"] = [
        {
            "name": "refund_approval",
            "when": "tool.name == 'issue_refund' and tool.args.amount > 100",
            "action": "require_approval",
            "approver_role": "supervisor",
        }
    ]
    return WorkflowVersionCreate.model_validate(payload)


def _create_queued_run(session: Session, *, message: str = "I was charged twice."):
    actor_user_id = uuid4()
    organization = services.create_organization(
        session,
        OrganizationCreate(name="Worker Org", slug=f"worker-org-{uuid4().hex[:8]}"),
        actor_user_id=actor_user_id,
    )
    project = services.create_project(
        session,
        org_id=organization.id,
        payload=ProjectCreate(name="Worker Project", slug=f"worker-project-{uuid4().hex[:8]}"),
        actor_user_id=actor_user_id,
    )
    workflow = services.create_workflow(
        session,
        project_id=project.id,
        payload=WorkflowCreate(
            slug="support-ticket-resolution",
            name="Support Ticket Resolution",
            domain="customer_support",
            description="Resolve customer support tickets.",
        ),
        actor_user_id=actor_user_id,
    )
    version = services.create_workflow_version(
        session,
        workflow_id=workflow.id,
        payload=_workflow_version_payload(),
        actor_user_id=actor_user_id,
    )
    version = services.publish_workflow_version(
        session,
        workflow_version_id=version.id,
        payload=PublishWorkflowVersionRequest(published_by=actor_user_id),
        actor_user_id=actor_user_id,
    )
    run = services.submit_workflow_run(
        session,
        project_id=project.id,
        workflow_slug=workflow.slug,
        payload=WorkflowRunSubmitRequest(
            input_payload={
                "ticket_id": "T-400",
                "customer_id": "C-500",
                "message": message,
            },
            triggered_by=actor_user_id,
        ),
        actor_user_id=actor_user_id,
    )
    return project, version, run


def _create_approval_queued_run(session: Session):
    actor_user_id = uuid4()
    organization = services.create_organization(
        session,
        OrganizationCreate(name="Approval Org", slug=f"approval-org-{uuid4().hex[:8]}"),
        actor_user_id=actor_user_id,
    )
    project = services.create_project(
        session,
        org_id=organization.id,
        payload=ProjectCreate(name="Approval Project", slug=f"approval-project-{uuid4().hex[:8]}"),
        actor_user_id=actor_user_id,
    )
    workflow = services.create_workflow(
        session,
        project_id=project.id,
        payload=WorkflowCreate(
            slug="support-ticket-resolution",
            name="Support Ticket Resolution",
            domain="customer_support",
            description="Resolve customer support tickets.",
        ),
        actor_user_id=actor_user_id,
    )
    version = services.create_workflow_version(
        session,
        workflow_id=workflow.id,
        payload=_approval_workflow_version_payload(),
        actor_user_id=actor_user_id,
    )
    version = services.publish_workflow_version(
        session,
        workflow_version_id=version.id,
        payload=PublishWorkflowVersionRequest(published_by=actor_user_id),
        actor_user_id=actor_user_id,
    )
    run = services.submit_workflow_run(
        session,
        project_id=project.id,
        workflow_slug=workflow.slug,
        payload=WorkflowRunSubmitRequest(
            input_payload={
                "ticket_id": "T-401",
                "customer_id": "C-500",
                "message": "I was charged twice and need a refund.",
            },
            triggered_by=actor_user_id,
        ),
        actor_user_id=actor_user_id,
    )
    return project, version, run


def test_deterministic_worker_executes_next_queued_run(db_session: Session) -> None:
    project, version, run = _create_queued_run(db_session)

    result = execute_next_queued_run(db_session, project_id=project.id)

    assert result is not None
    assert result.project_id == project.id
    assert result.run_id == run.id
    assert result.workflow_version_id == version.id
    assert result.status == RunStatus.SUCCEEDED
    assert result.final_output is not None
    assert result.final_output["disposition"] == "resolved"

    db_session.refresh(run)
    assert run.status == RunStatus.SUCCEEDED
    assert run.started_at is not None
    assert run.ended_at is not None
    assert run.latency_ms is not None
    assert run.final_output_json is not None
    assert run.final_output_json["summary"].startswith("Processed ticket T-400")
    assert "Avery Stone" in run.final_output_json["summary"]
    assert "Handling duplicate charges" in run.final_output_json["summary"]
    assert run.tokens_input is not None
    assert run.tokens_output is not None

    spans = services.list_trace_spans(db_session, project_id=project.id, run_id=run.id)
    assert [span.span_type for span in spans] == [
        "run.start",
        "agent.step",
        "tool.proposed",
        "tool.execute",
        "tool.proposed",
        "tool.execute",
        "tool.proposed",
        "tool.execute",
        "output.validate",
        "run.finish",
    ]
    assert {span.workflow_version_id for span in spans} == {version.id}
    assert spans[-1].status == SpanStatus.OK

    tool_calls = services.list_tool_calls(db_session, project_id=project.id, run_id=run.id)
    assert [tool_call.tool_name for tool_call in tool_calls] == [
        "kb_search",
        "get_customer_profile",
        "get_order",
    ]
    assert {tool_call.status for tool_call in tool_calls} == {ToolCallStatus.EXECUTED}
    assert tool_calls[0].result_json is not None
    assert tool_calls[0].result_json["articles"][0]["article_id"] == "KB-100"
    assert tool_calls[1].result_json is not None
    assert tool_calls[1].result_json["name"] == "Avery Stone"
    assert tool_calls[2].result_json is not None
    assert tool_calls[2].result_json["order_id"] == "O-900"

    with pytest.raises(ConflictError, match="worker can only execute queued or resumed runs"):
        execute_run(db_session, project_id=project.id, run_id=run.id)


def test_deterministic_worker_marks_failed_tool_call_and_run_failure(db_session: Session) -> None:
    project, _, run = _create_queued_run(db_session, message="__force_tool_failure__")

    result = execute_run(db_session, project_id=project.id, run_id=run.id)

    assert result.status == RunStatus.FAILED
    assert result.final_output is None

    db_session.refresh(run)
    assert run.status == RunStatus.FAILED
    assert run.final_output_json is None

    spans = services.list_trace_spans(db_session, project_id=project.id, run_id=run.id)
    finish_span = spans[-1]
    assert finish_span.span_type == "run.finish"
    assert finish_span.status == SpanStatus.ERROR
    assert finish_span.error_json == {
        "type": "SupportToolError",
        "message": "forced support demo tool failure",
    }

    tool_calls = services.list_tool_calls(db_session, project_id=project.id, run_id=run.id)
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "kb_search"
    assert tool_calls[0].status == ToolCallStatus.FAILED
    assert tool_calls[0].error_json == {
        "type": "SupportToolError",
        "message": "forced support demo tool failure",
    }


def test_deterministic_worker_returns_none_when_no_queued_runs(db_session: Session) -> None:
    assert execute_next_queued_run(db_session) is None


def test_deterministic_worker_pauses_for_refund_approval_and_resumes(db_session: Session) -> None:
    project, version, run = _create_approval_queued_run(db_session)

    first_result = execute_run(db_session, project_id=project.id, run_id=run.id)

    assert first_result.status == RunStatus.AWAITING_APPROVAL
    assert first_result.final_output is None
    db_session.refresh(run)
    assert run.status == RunStatus.AWAITING_APPROVAL

    approvals = services.list_approval_requests(
        db_session,
        project_id=project.id,
        status=ApprovalStatus.PENDING,
    )
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.run_id == run.id
    assert approval.approver_role == MembershipRole.SUPERVISOR
    assert approval.proposed_effect_json is not None
    assert approval.proposed_effect_json["tool_name"] == "issue_refund"
    assert approval.proposed_effect_json["args"]["amount"] == 149.0

    tool_calls = services.list_tool_calls(db_session, project_id=project.id, run_id=run.id)
    refund_call = next(tool_call for tool_call in tool_calls if tool_call.tool_name == "issue_refund")
    assert refund_call.status == ToolCallStatus.PROPOSED
    assert refund_call.approval_required is True
    assert refund_call.approval_id == approval.id

    decided = services.decide_approval_request(
        db_session,
        project_id=project.id,
        approval_id=approval.id,
        status=ApprovalStatus.APPROVED,
        decided_by=uuid4(),
        decision_note="Duplicate charge confirmed.",
    )
    assert decided.status == ApprovalStatus.APPROVED
    db_session.refresh(run)
    assert run.status == RunStatus.RESUMED

    second_result = execute_run(db_session, project_id=project.id, run_id=run.id)

    assert second_result.status == RunStatus.SUCCEEDED
    assert second_result.workflow_version_id == version.id
    assert second_result.final_output is not None
    assert second_result.final_output["disposition"] == "resolved"

    tool_calls = services.list_tool_calls(db_session, project_id=project.id, run_id=run.id)
    refund_call = next(tool_call for tool_call in tool_calls if tool_call.tool_name == "issue_refund")
    assert refund_call.status == ToolCallStatus.EXECUTED
    assert refund_call.result_json is not None
    assert refund_call.result_json["status"] == "issued"
    assert refund_call.result_json["amount"] == 149.0

    spans = services.list_trace_spans(db_session, project_id=project.id, run_id=run.id)
    assert "approval.wait" in [span.span_type for span in spans]
    assert "run.resume" in [span.span_type for span in spans]
