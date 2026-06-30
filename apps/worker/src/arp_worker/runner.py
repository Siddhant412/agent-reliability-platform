from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JSONSchemaValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from arp_core.application import services
from arp_core.application.exceptions import ConflictError, NotFoundError
from arp_core.application.policies import evaluate_policy_pack
from arp_core.contracts.run import RunTransitionRequest, ToolCallCreate, ToolCallUpdate, TraceSpanCreate
from arp_core.domain.enums import PolicyAction, RunStatus, SpanStatus, ToolCallStatus
from arp_core.persistence.models import Run, ToolCall, WorkflowVersion
from arp_support_demo.tools import SupportToolError, execute_tool


class DeterministicWorkerError(Exception):
    """Raised for deterministic demo failures that should be persisted on the run."""


@dataclass(frozen=True)
class WorkerExecutionResult:
    project_id: UUID
    run_id: UUID
    workflow_version_id: UUID
    status: RunStatus
    trace_id: str
    final_output: dict[str, Any] | None


def _stable_hex(value: str, *, length: int) -> str:
    return uuid5(NAMESPACE_URL, value).hex[:length]


def _load_run(session: Session, *, project_id: UUID, run_id: UUID) -> Run:
    run = session.scalar(
        select(Run)
        .options(joinedload(Run.workflow_version).joinedload(WorkflowVersion.workflow))
        .where(Run.project_id == project_id, Run.id == run_id)
    )
    if run is None:
        raise NotFoundError("run not found")
    return run


def _load_executable_run(session: Session, *, project_id: UUID, run_id: UUID) -> Run:
    run = _load_run(session, project_id=project_id, run_id=run_id)
    if run.status not in {RunStatus.QUEUED, RunStatus.RESUMED}:
        raise ConflictError("worker can only execute queued or resumed runs")
    return run


def _next_queued_run(session: Session, *, project_id: UUID | None = None) -> Run | None:
    statement = (
        select(Run)
        .options(joinedload(Run.workflow_version).joinedload(WorkflowVersion.workflow))
        .where(Run.status == RunStatus.QUEUED)
        .order_by(Run.created_at)
    )
    if project_id is not None:
        statement = statement.where(Run.project_id == project_id)
    return session.scalar(statement)


def _span(
    *,
    run_id: UUID,
    trace_id: str,
    span_type: str,
    name: str,
    status: SpanStatus,
    parent_span_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> TraceSpanCreate:
    return TraceSpanCreate(
        trace_id=trace_id,
        span_id=_stable_hex(f"{run_id}:{span_type}:{name}", length=16),
        parent_span_id=parent_span_id,
        span_type=span_type,
        name=name,
        status=status,
        attributes=attributes or {},
        error=error,
    )


def _emit_span(session: Session, *, project_id: UUID, run_id: UUID, payload: TraceSpanCreate) -> None:
    services.create_trace_span(session, project_id=project_id, run_id=run_id, payload=payload)


def _tool_plan(run: Run) -> list[tuple[str, dict[str, Any]]]:
    input_payload = run.input_json
    return [
        ("kb_search", {"query": input_payload.get("message", "")}),
        ("get_customer_profile", {"customer_id": input_payload.get("customer_id", "")}),
        ("get_order", {"customer_id": input_payload.get("customer_id", "")}),
    ]


def _workflow_tool_names(run: Run) -> set[str]:
    names: set[str] = set()
    for item in run.workflow_version.tool_set_json:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and "name" in item:
            names.add(str(item["name"]))
    return names


def _needs_refund(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in ("refund", "charged", "charge", "double", "duplicate"))


def _mutating_tool_plan(run: Run, tool_results: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    if not run.workflow_version.policy_pack_json:
        return []

    tool_names = _workflow_tool_names(run)
    input_payload = run.input_json
    ticket_id = str(input_payload.get("ticket_id", "unknown-ticket"))
    customer_id = str(input_payload.get("customer_id", "unknown-customer"))
    message = str(input_payload.get("message", ""))
    order = tool_results.get("get_order", {})
    order_id = str(order.get("order_id", ""))
    order_total = float(order.get("total_usd") or 0)

    plan: list[tuple[str, dict[str, Any]]] = []
    if "issue_refund" in tool_names and order_id and _needs_refund(message):
        plan.append(
            (
                "issue_refund",
                {
                    "order_id": order_id,
                    "amount": order_total,
                    "reason": f"Customer reported a billing issue on ticket {ticket_id}.",
                    "idempotency_key": f"{run.id}:issue_refund:{order_id}",
                },
            )
        )
    if "post_ticket_comment" in tool_names:
        plan.append(
            (
                "post_ticket_comment",
                {
                    "ticket_id": ticket_id,
                    "body": "Investigated customer context and prepared the next safe action.",
                    "idempotency_key": f"{run.id}:post_ticket_comment:{ticket_id}",
                },
            )
        )
    if "send_customer_email" in tool_names and input_payload.get("priority") == "high":
        plan.append(
            (
                "send_customer_email",
                {
                    "customer_id": customer_id,
                    "subject": f"Update on ticket {ticket_id}",
                    "body": "We reviewed your request and prepared the next steps.",
                    "idempotency_key": f"{run.id}:send_customer_email:{ticket_id}",
                },
            )
        )
    return plan


def _execute_tool_call(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    trace_id: str,
    tool_call: ToolCall,
    tool_name: str,
    args: dict[str, Any],
    parent_span_id: str | None,
) -> dict[str, Any]:
    try:
        result = execute_tool(tool_name, args)
    except SupportToolError as exc:
        execute_span = _span(
            run_id=run_id,
            trace_id=trace_id,
            span_type="tool.execute",
            name=f"tool.execute.{tool_name}",
            status=SpanStatus.ERROR,
            parent_span_id=parent_span_id,
            attributes={"tool_name": tool_name},
            error={"type": exc.__class__.__name__, "message": str(exc)},
        )
        _emit_span(session, project_id=project_id, run_id=run_id, payload=execute_span)
        services.update_tool_call(
            session,
            project_id=project_id,
            tool_call_id=tool_call.id,
            payload=ToolCallUpdate(
                status=ToolCallStatus.FAILED,
                span_id=execute_span.span_id,
                error={"type": exc.__class__.__name__, "message": str(exc)},
            ),
        )
        raise

    execute_span = _span(
        run_id=run_id,
        trace_id=trace_id,
        span_type="tool.execute",
        name=f"tool.execute.{tool_name}",
        status=SpanStatus.OK,
        parent_span_id=parent_span_id,
        attributes={"tool_name": tool_name},
    )
    _emit_span(session, project_id=project_id, run_id=run_id, payload=execute_span)
    services.update_tool_call(
        session,
        project_id=project_id,
        tool_call_id=tool_call.id,
        payload=ToolCallUpdate(status=ToolCallStatus.EXECUTED, span_id=execute_span.span_id, result=result),
    )
    return result


def _run_support_tool(
    session: Session,
    *,
    project_id: UUID,
    run_id: UUID,
    trace_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    proposed_span = _span(
        run_id=run_id,
        trace_id=trace_id,
        span_type="tool.proposed",
        name=f"tool.proposed.{tool_name}",
        status=SpanStatus.OK,
        attributes={"tool_name": tool_name},
    )
    _emit_span(session, project_id=project_id, run_id=run_id, payload=proposed_span)
    tool_call = services.create_tool_call(
        session,
        project_id=project_id,
        run_id=run_id,
        payload=ToolCallCreate(tool_name=tool_name, args=args, span_id=proposed_span.span_id),
    )

    return _execute_tool_call(
        session,
        project_id=project_id,
        run_id=run_id,
        trace_id=trace_id,
        tool_call=tool_call,
        tool_name=tool_name,
        args=args,
        parent_span_id=proposed_span.span_id,
    )


def _run_policy_gated_tool(
    session: Session,
    *,
    run: Run,
    trace_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> str:
    proposed_span = _span(
        run_id=run.id,
        trace_id=trace_id,
        span_type="tool.proposed",
        name=f"tool.proposed.{tool_name}",
        status=SpanStatus.OK,
        attributes={"tool_name": tool_name, "mutating": True},
    )
    _emit_span(session, project_id=run.project_id, run_id=run.id, payload=proposed_span)
    tool_call = services.create_tool_call(
        session,
        project_id=run.project_id,
        run_id=run.id,
        payload=ToolCallCreate(
            tool_name=tool_name,
            args=args,
            span_id=proposed_span.span_id,
            approval_required=True,
        ),
    )

    decision = evaluate_policy_pack(
        run.workflow_version.policy_pack_json,
        tool_name=tool_name,
        tool_args=args,
        input_payload=run.input_json,
    )
    _emit_span(
        session,
        project_id=run.project_id,
        run_id=run.id,
        payload=_span(
            run_id=run.id,
            trace_id=trace_id,
            span_type="policy.evaluate",
            name=f"policy.evaluate.{tool_name}",
            status=SpanStatus.OK,
            parent_span_id=proposed_span.span_id,
            attributes={
                "tool_name": tool_name,
                "action": decision.action.value,
                "policy_name": decision.policy_name,
            },
        ),
    )

    if decision.action == PolicyAction.DENY:
        services.update_tool_call(
            session,
            project_id=run.project_id,
            tool_call_id=tool_call.id,
            payload=ToolCallUpdate(status=ToolCallStatus.BLOCKED),
        )
        return "blocked"

    if decision.action == PolicyAction.REQUIRE_APPROVAL:
        if decision.approver_role is None:
            services.update_tool_call(
                session,
                project_id=run.project_id,
                tool_call_id=tool_call.id,
                payload=ToolCallUpdate(status=ToolCallStatus.FAILED, error={"message": "missing approver role"}),
            )
            raise DeterministicWorkerError("policy requires approval but no approver role was configured")
        approval = services.create_approval_request(
            session,
            project_id=run.project_id,
            run_id=run.id,
            tool_call_id=tool_call.id,
            approver_role=decision.approver_role,
            reason=decision.reason or f"{tool_name} requires approval",
            run_context={
                "input": run.input_json,
                "workflow_version_id": str(run.workflow_version_id),
            },
            proposed_effect={"tool_name": tool_name, "args": args},
        )
        _emit_span(
            session,
            project_id=run.project_id,
            run_id=run.id,
            payload=_span(
                run_id=run.id,
                trace_id=trace_id,
                span_type="approval.wait",
                name=f"approval.wait.{tool_name}",
                status=SpanStatus.IN_PROGRESS,
                parent_span_id=proposed_span.span_id,
                attributes={
                    "approval_id": str(approval.id),
                    "approver_role": approval.approver_role.value,
                },
            ),
        )
        services.transition_run_status(
            session,
            project_id=run.project_id,
            run_id=run.id,
            payload=RunTransitionRequest(status=RunStatus.AWAITING_APPROVAL),
        )
        return "awaiting_approval"

    _execute_tool_call(
        session,
        project_id=run.project_id,
        run_id=run.id,
        trace_id=trace_id,
        tool_call=tool_call,
        tool_name=tool_name,
        args=args,
        parent_span_id=proposed_span.span_id,
    )
    return "executed"


def _persisted_tool_results(session: Session, *, project_id: UUID, run_id: UUID) -> dict[str, dict[str, Any]]:
    return {
        tool_call.tool_name: tool_call.result_json or {}
        for tool_call in services.list_tool_calls(session, project_id=project_id, run_id=run_id)
        if tool_call.status == ToolCallStatus.EXECUTED
    }


def _execute_approved_tool_calls(session: Session, *, run: Run, trace_id: str) -> None:
    for tool_call in services.list_tool_calls(session, project_id=run.project_id, run_id=run.id):
        if tool_call.status != ToolCallStatus.APPROVED:
            continue
        _execute_tool_call(
            session,
            project_id=run.project_id,
            run_id=run.id,
            trace_id=trace_id,
            tool_call=tool_call,
            tool_name=tool_call.tool_name,
            args=tool_call.args_json,
            parent_span_id=tool_call.span_id,
        )


def _has_rejected_tool_calls(session: Session, *, project_id: UUID, run_id: UUID) -> bool:
    return any(
        tool_call.status == ToolCallStatus.REJECTED
        for tool_call in services.list_tool_calls(session, project_id=project_id, run_id=run_id)
    )


def _finish_run(
    session: Session,
    *,
    run: Run,
    trace_id: str,
    final_output: dict[str, Any],
) -> WorkerExecutionResult:
    try:
        Draft202012Validator.check_schema(run.workflow_version.output_schema_json)
        Draft202012Validator(run.workflow_version.output_schema_json).validate(final_output)
    except SchemaError as exc:
        raise DeterministicWorkerError(f"workflow output_schema is invalid: {exc.message}") from exc
    except JSONSchemaValidationError as exc:
        location = "final_output"
        for path_part in exc.absolute_path:
            if isinstance(path_part, int):
                location += f"[{path_part}]"
            else:
                location += f".{path_part}"
        raise DeterministicWorkerError(f"{location}: {exc.message}") from exc

    _emit_span(
        session,
        project_id=run.project_id,
        run_id=run.id,
        payload=_span(
            run_id=run.id,
            trace_id=trace_id,
            span_type="output.validate",
            name="output.validate",
            status=SpanStatus.OK,
            attributes={"schema": "workflow.output_schema"},
        ),
    )
    _emit_span(
        session,
        project_id=run.project_id,
        run_id=run.id,
        payload=_span(
            run_id=run.id,
            trace_id=trace_id,
            span_type="run.finish",
            name="run.finish",
            status=SpanStatus.OK,
        ),
    )
    run = services.transition_run_status(
        session,
        project_id=run.project_id,
        run_id=run.id,
        payload=RunTransitionRequest(
            status=RunStatus.SUCCEEDED,
            final_output=final_output,
            tokens_input=_token_count(run.input_json),
            tokens_output=_token_count(final_output),
        ),
    )
    return WorkerExecutionResult(
        project_id=run.project_id,
        run_id=run.id,
        workflow_version_id=run.workflow_version_id,
        status=run.status,
        trace_id=trace_id,
        final_output=run.final_output_json,
    )


def _build_output(
    run: Run,
    tool_results: dict[str, dict[str, Any]],
    *,
    rejected_action: bool = False,
) -> dict[str, Any]:
    input_payload = run.input_json
    ticket_id = input_payload.get("ticket_id", "unknown-ticket")
    customer_id = input_payload.get("customer_id", "unknown-customer")
    message = input_payload.get("message", "")
    if message == "__force_worker_failure__":
        raise DeterministicWorkerError("forced deterministic worker failure")

    customer = tool_results["get_customer_profile"]
    order = tool_results["get_order"]
    articles = tool_results["kb_search"]["articles"]
    article_title = articles[0]["title"] if articles else "Customer reply quality"
    customer_name = customer.get("name") or "Unknown Customer"
    customer_tier = customer.get("tier", "standard")
    order_id = order.get("order_id", "no-order")
    order_status = order.get("status", "unknown")
    disposition = "escalated" if rejected_action else "resolved"
    proposed_action = (
        {
            "tool": "manual_review",
            "reason": "A requested action was rejected and needs a safer follow-up.",
        }
        if rejected_action
        else {
            "tool": "post_ticket_comment",
            "reason": f"Record the resolution using {article_title}.",
        }
    )

    return {
        "summary": (
            f"Processed ticket {ticket_id} for {customer_name} ({customer_id}, {customer_tier}). "
            f"Matched guidance '{article_title}' and latest order {order_id} is {order_status}. "
            f"Customer message: {message}"
        ),
        "disposition": disposition,
        "proposed_actions": [proposed_action],
        "customer_reply": (
            f"Thanks for contacting support. We reviewed your {customer_tier} account and latest order "
            "details, and prepared the next steps."
        ),
        "confidence": 0.82,
    }


def _token_count(value: Any) -> int:
    return len(str(value).split())


def execute_run(session: Session, *, project_id: UUID, run_id: UUID) -> WorkerExecutionResult:
    run = _load_executable_run(session, project_id=project_id, run_id=run_id)
    trace_id = _stable_hex(f"run:{run.id}", length=32)
    workflow = run.workflow_version.workflow
    is_resumed = run.status == RunStatus.RESUMED

    services.transition_run_status(
        session,
        project_id=project_id,
        run_id=run_id,
        payload=RunTransitionRequest(status=RunStatus.RUNNING),
    )
    _emit_span(
        session,
        project_id=project_id,
        run_id=run_id,
        payload=_span(
            run_id=run_id,
            trace_id=trace_id,
            span_type="run.resume" if is_resumed else "run.start",
            name="run.resume" if is_resumed else "run.start",
            status=SpanStatus.OK,
            attributes={
                "workflow_slug": workflow.slug,
                "workflow_version": run.workflow_version.version,
            },
        ),
    )

    try:
        _emit_span(
            session,
            project_id=project_id,
            run_id=run_id,
            payload=_span(
                run_id=run_id,
                trace_id=trace_id,
                span_type="agent.step",
                name="deterministic.resume" if is_resumed else "deterministic.output",
                status=SpanStatus.OK,
                attributes={"runtime": "deterministic"},
            ),
        )

        if is_resumed:
            _execute_approved_tool_calls(session, run=run, trace_id=trace_id)
            tool_results = _persisted_tool_results(session, project_id=project_id, run_id=run_id)
            final_output = _build_output(
                run,
                tool_results,
                rejected_action=_has_rejected_tool_calls(session, project_id=project_id, run_id=run_id),
            )
            return _finish_run(session, run=run, trace_id=trace_id, final_output=final_output)

        tool_results = {}
        for tool_name, args in _tool_plan(run):
            tool_results[tool_name] = _run_support_tool(
                session,
                project_id=project_id,
                run_id=run_id,
                trace_id=trace_id,
                tool_name=tool_name,
                args=args,
            )

        for tool_name, args in _mutating_tool_plan(run, tool_results):
            outcome = _run_policy_gated_tool(
                session,
                run=run,
                trace_id=trace_id,
                tool_name=tool_name,
                args=args,
            )
            if outcome == "awaiting_approval":
                return WorkerExecutionResult(
                    project_id=project_id,
                    run_id=run_id,
                    workflow_version_id=run.workflow_version_id,
                    status=RunStatus.AWAITING_APPROVAL,
                    trace_id=trace_id,
                    final_output=None,
                )

        final_output = _build_output(run, tool_results)
        return _finish_run(session, run=run, trace_id=trace_id, final_output=final_output)
    except (DeterministicWorkerError, SupportToolError) as exc:
        _emit_span(
            session,
            project_id=project_id,
            run_id=run_id,
            payload=_span(
                run_id=run_id,
                trace_id=trace_id,
                span_type="run.finish",
                name="run.finish",
                status=SpanStatus.ERROR,
                error={"type": exc.__class__.__name__, "message": str(exc)},
            ),
        )
        run = services.transition_run_status(
            session,
            project_id=project_id,
            run_id=run_id,
            payload=RunTransitionRequest(status=RunStatus.FAILED),
        )
        return WorkerExecutionResult(
            project_id=project_id,
            run_id=run_id,
            workflow_version_id=run.workflow_version_id,
            status=run.status,
            trace_id=trace_id,
            final_output=run.final_output_json,
        )


def execute_next_queued_run(session: Session, *, project_id: UUID | None = None) -> WorkerExecutionResult | None:
    run = _next_queued_run(session, project_id=project_id)
    if run is None:
        return None
    return execute_run(session, project_id=run.project_id, run_id=run.id)
