from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from arp_core.application import services
from arp_core.application.exceptions import ConflictError, NotFoundError
from arp_core.contracts.run import RunTransitionRequest, ToolCallCreate, ToolCallUpdate, TraceSpanCreate
from arp_core.domain.enums import RunStatus, SpanStatus, ToolCallStatus
from arp_core.persistence.models import Run, WorkflowVersion
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


def _load_queued_run(session: Session, *, project_id: UUID, run_id: UUID) -> Run:
    run = _load_run(session, project_id=project_id, run_id=run_id)
    if run.status != RunStatus.QUEUED:
        raise ConflictError("worker can only execute queued runs")
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

    try:
        result = execute_tool(tool_name, args)
    except SupportToolError as exc:
        execute_span = _span(
            run_id=run_id,
            trace_id=trace_id,
            span_type="tool.execute",
            name=f"tool.execute.{tool_name}",
            status=SpanStatus.ERROR,
            parent_span_id=proposed_span.span_id,
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
        parent_span_id=proposed_span.span_id,
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


def _build_output(run: Run, tool_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
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

    return {
        "summary": (
            f"Processed ticket {ticket_id} for {customer_name} ({customer_id}, {customer_tier}). "
            f"Matched guidance '{article_title}' and latest order {order_id} is {order_status}. "
            f"Customer message: {message}"
        ),
        "disposition": "resolved",
        "proposed_actions": [
            {
                "tool": "post_ticket_comment",
                "reason": f"Record the resolution using {article_title}.",
            }
        ],
        "customer_reply": (
            f"Thanks for contacting support. We reviewed your {customer_tier} account and latest order "
            "details, and prepared the next steps."
        ),
        "confidence": 0.82,
    }


def _token_count(value: Any) -> int:
    return len(str(value).split())


def execute_run(session: Session, *, project_id: UUID, run_id: UUID) -> WorkerExecutionResult:
    run = _load_queued_run(session, project_id=project_id, run_id=run_id)
    trace_id = _stable_hex(f"run:{run.id}", length=32)
    workflow = run.workflow_version.workflow

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
            span_type="run.start",
            name="run.start",
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
                name="deterministic.output",
                status=SpanStatus.OK,
                attributes={"runtime": "deterministic"},
            ),
        )
        tool_results = {
            tool_name: _run_support_tool(
                session,
                project_id=project_id,
                run_id=run_id,
                trace_id=trace_id,
                tool_name=tool_name,
                args=args,
            )
            for tool_name, args in _tool_plan(run)
        }
        final_output = _build_output(run, tool_results)
        _emit_span(
            session,
            project_id=project_id,
            run_id=run_id,
            payload=_span(
                run_id=run_id,
                trace_id=trace_id,
                span_type="output.validate",
                name="output.validate",
                status=SpanStatus.OK,
                attributes={"schema": "workflow.output_schema"},
            ),
        )
        _emit_span(
            session,
            project_id=project_id,
            run_id=run_id,
            payload=_span(
                run_id=run_id,
                trace_id=trace_id,
                span_type="run.finish",
                name="run.finish",
                status=SpanStatus.OK,
            ),
        )
        run = services.transition_run_status(
            session,
            project_id=project_id,
            run_id=run_id,
            payload=RunTransitionRequest(
                status=RunStatus.SUCCEEDED,
                final_output=final_output,
                tokens_input=_token_count(run.input_json),
                tokens_output=_token_count(final_output),
            ),
        )
        return WorkerExecutionResult(
            project_id=project_id,
            run_id=run_id,
            workflow_version_id=run.workflow_version_id,
            status=run.status,
            trace_id=trace_id,
            final_output=run.final_output_json,
        )
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
