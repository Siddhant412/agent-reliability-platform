from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from arp_core.application import services
from arp_core.application.exceptions import ApplicationError
from arp_core.contracts.run import RunSubmitRequest
from arp_core.domain.enums import ApprovalStatus, EvalCaseStatus, EvalRunStatus, RunStatus, ToolCallStatus
from arp_core.persistence.models import Dataset, EvalRun
from arp_core.persistence.base import utcnow
from arp_worker.runner import execute_run


@dataclass(frozen=True)
class EvalExecutionResult:
    project_id: UUID
    eval_run_id: UUID
    status: EvalRunStatus
    summary: dict[str, Any]


@dataclass(frozen=True)
class EvalAttemptResult:
    run_id: UUID | None
    succeeded: bool
    schema_valid: bool
    failed_tool_calls: int
    unresolved_approvals: int
    final_status: str | None
    output: dict[str, Any] | None
    trace_grade: dict[str, Any] | None
    error: dict[str, Any] | None

    def scores(self) -> dict[str, Any]:
        return {
            "run_succeeded": self.final_status == RunStatus.SUCCEEDED.value,
            "output_schema_valid": self.schema_valid,
            "failed_tool_calls": self.failed_tool_calls,
            "unresolved_approvals": self.unresolved_approvals,
            "final_status": self.final_status,
        }


def execute_eval_run(
    session: Session,
    *,
    project_id: UUID,
    eval_run_id: UUID,
    claimed: bool = False,
) -> EvalExecutionResult:
    eval_run = services.get_eval_run(session, project_id=project_id, eval_run_id=eval_run_id) if claimed else (
        services.mark_eval_run_running(session, project_id=project_id, eval_run_id=eval_run_id)
    )
    if claimed and eval_run.status != EvalRunStatus.RUNNING:
        raise ApplicationError("claimed eval run is no longer running")
    cases = services.list_eval_cases(session, project_id=project_id, dataset_id=eval_run.dataset_id)

    totals = {
        "total_cases": len(cases),
        "succeeded": 0,
        "failed": 0,
        "schema_valid": 0,
        "failed_tool_calls": 0,
        "unresolved_approvals": 0,
        "baseline_succeeded": 0,
        "baseline_failed": 0,
        "baseline_schema_valid": 0,
        "candidate_better": 0,
        "candidate_worse": 0,
        "unchanged": 0,
    }

    try:
        for eval_case in cases:
            case_summary = _execute_eval_case(
                session,
                project_id=project_id,
                eval_run_id=eval_run_id,
                workflow_version_id=eval_run.workflow_version_id,
                baseline_version_id=eval_run.baseline_version_id,
                eval_case_id=eval_case.id,
                input_payload=eval_case.input_json,
            )
            totals["failed_tool_calls"] += case_summary["failed_tool_calls"]
            totals["unresolved_approvals"] += case_summary["unresolved_approvals"]
            if case_summary["succeeded"]:
                totals["succeeded"] += 1
            else:
                totals["failed"] += 1
            if case_summary["schema_valid"]:
                totals["schema_valid"] += 1
            if case_summary["baseline_present"]:
                if case_summary["baseline_succeeded"]:
                    totals["baseline_succeeded"] += 1
                else:
                    totals["baseline_failed"] += 1
                if case_summary["baseline_schema_valid"]:
                    totals["baseline_schema_valid"] += 1
                comparison = case_summary["comparison"]
                if comparison in {"candidate_better", "candidate_worse", "unchanged"}:
                    totals[comparison] += 1

        total_cases = totals["total_cases"]
        baseline_cases = totals["baseline_succeeded"] + totals["baseline_failed"]
        summary = {
            **totals,
            "success_rate": (totals["succeeded"] / total_cases) if total_cases else 0,
            "schema_valid_rate": (totals["schema_valid"] / total_cases) if total_cases else 0,
            "baseline_success_rate": (totals["baseline_succeeded"] / baseline_cases) if baseline_cases else None,
            "baseline_schema_valid_rate": (
                (totals["baseline_schema_valid"] / baseline_cases) if baseline_cases else None
            ),
        }
        eval_run = services.finish_eval_run(
            session,
            project_id=project_id,
            eval_run_id=eval_run_id,
            status=EvalRunStatus.SUCCEEDED,
            summary=summary,
        )
    except Exception:
        summary = {
            **totals,
            "success_rate": (totals["succeeded"] / totals["total_cases"]) if totals["total_cases"] else 0,
            "schema_valid_rate": (totals["schema_valid"] / totals["total_cases"]) if totals["total_cases"] else 0,
            "baseline_success_rate": None,
            "baseline_schema_valid_rate": None,
            "runner_error": True,
        }
        eval_run = services.finish_eval_run(
            session,
            project_id=project_id,
            eval_run_id=eval_run_id,
            status=EvalRunStatus.FAILED,
            summary=summary,
        )
        raise

    return EvalExecutionResult(
        project_id=project_id,
        eval_run_id=eval_run.id,
        status=eval_run.status,
        summary=eval_run.summary_json,
    )


def execute_next_queued_eval_run(
    session: Session,
    *,
    project_id: UUID | None = None,
    claim_ttl_seconds: int = 300,
) -> EvalExecutionResult | None:
    now = utcnow()
    session.query(EvalRun).filter(
        EvalRun.status == EvalRunStatus.RUNNING,
        EvalRun.claim_expires_at.is_not(None),
        EvalRun.claim_expires_at <= now,
    ).update(
        {
            EvalRun.status: EvalRunStatus.QUEUED,
            EvalRun.claim_token: None,
            EvalRun.claimed_at: None,
            EvalRun.claim_expires_at: None,
        },
        synchronize_session=False,
    )
    statement = (
        select(EvalRun)
        .join(Dataset, Dataset.id == EvalRun.dataset_id)
        .where(EvalRun.status == EvalRunStatus.QUEUED)
        .order_by(EvalRun.created_at)
        .with_for_update(of=EvalRun, skip_locked=True)
    )
    if project_id is not None:
        statement = statement.where(Dataset.project_id == project_id)
    eval_run = session.scalar(statement)
    if eval_run is None:
        return None
    eval_project_id = session.scalar(select(Dataset.project_id).where(Dataset.id == eval_run.dataset_id))
    if eval_project_id is None:
        return None
    eval_run.status = EvalRunStatus.RUNNING
    eval_run.claim_token = uuid4().hex
    eval_run.claimed_at = now
    eval_run.claim_expires_at = now + timedelta(seconds=claim_ttl_seconds)
    eval_run.attempt_count += 1
    if eval_run.started_at is None:
        eval_run.started_at = now
    session.flush()
    return execute_eval_run(session, project_id=eval_project_id, eval_run_id=eval_run.id, claimed=True)


def _execute_eval_case(
    session: Session,
    *,
    project_id: UUID,
    eval_run_id: UUID,
    workflow_version_id: UUID,
    baseline_version_id: UUID | None,
    eval_case_id: UUID,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    candidate = _execute_eval_attempt(
        session,
        project_id=project_id,
        workflow_version_id=workflow_version_id,
        input_payload=input_payload,
    )
    baseline = (
        _execute_eval_attempt(
            session,
            project_id=project_id,
            workflow_version_id=baseline_version_id,
            input_payload=input_payload,
        )
        if baseline_version_id is not None
        else None
    )
    comparison = _compare_attempts(candidate=candidate, baseline=baseline)
    scores = {
        **candidate.scores(),
        "candidate": candidate.scores(),
        "baseline": baseline.scores() if baseline is not None else None,
        "comparison": comparison,
    }
    trace_grade = candidate.trace_grade or {}
    if baseline is not None and baseline.trace_grade is not None:
        trace_grade = {**trace_grade, "baseline": baseline.trace_grade}

    services.create_eval_case_result(
        session,
        project_id=project_id,
        eval_run_id=eval_run_id,
        eval_case_id=eval_case_id,
        run_id=candidate.run_id,
        status=EvalCaseStatus.SUCCEEDED if candidate.succeeded else EvalCaseStatus.FAILED,
        scores=scores,
        output=candidate.output,
        trace_grade=trace_grade or None,
        error=candidate.error if candidate.error is not None else None,
    )
    return {
        "succeeded": candidate.succeeded,
        "schema_valid": candidate.schema_valid,
        "failed_tool_calls": candidate.failed_tool_calls,
        "unresolved_approvals": candidate.unresolved_approvals,
        "baseline_present": baseline is not None,
        "baseline_succeeded": baseline.succeeded if baseline is not None else False,
        "baseline_schema_valid": baseline.schema_valid if baseline is not None else False,
        "comparison": comparison,
    }


def _execute_eval_attempt(
    session: Session,
    *,
    project_id: UUID,
    workflow_version_id: UUID,
    input_payload: dict[str, Any],
) -> EvalAttemptResult:
    run_id: UUID | None = None
    try:
        run = services.submit_run(
            session,
            project_id=project_id,
            payload=RunSubmitRequest(workflow_version_id=workflow_version_id, input_payload=input_payload),
            actor_user_id=None,
        )
        run_id = run.id
        execution = execute_run(session, project_id=project_id, run_id=run.id)
        run = services.get_run(session, project_id=project_id, run_id=run.id)
        failed_tool_calls = len(
            [
                tool_call
                for tool_call in services.list_tool_calls(session, project_id=project_id, run_id=run.id)
                if tool_call.status == ToolCallStatus.FAILED
            ]
        )
        unresolved_approvals = len(
            services.list_approval_requests(
                session,
                project_id=project_id,
                run_id=run.id,
                status=ApprovalStatus.PENDING,
            )
        )
        schema_valid = run.status == RunStatus.SUCCEEDED and run.final_output_json is not None
        succeeded = schema_valid and failed_tool_calls == 0 and unresolved_approvals == 0
        return EvalAttemptResult(
            run_id=run.id,
            succeeded=succeeded,
            schema_valid=schema_valid,
            failed_tool_calls=failed_tool_calls,
            unresolved_approvals=unresolved_approvals,
            final_status=run.status.value,
            output=run.final_output_json,
            trace_grade={
                "run_id": str(run.id),
                "trace_id": execution.trace_id,
                "span_count": len(services.list_trace_spans(session, project_id=project_id, run_id=run.id)),
            },
            error=None if succeeded else {"message": "case did not satisfy eval success criteria"},
        )
    except ApplicationError as exc:
        return EvalAttemptResult(
            run_id=run_id,
            succeeded=False,
            schema_valid=False,
            failed_tool_calls=0,
            unresolved_approvals=0,
            final_status=None,
            output=None,
            trace_grade=None,
            error={"type": exc.__class__.__name__, "message": str(exc)},
        )


def _compare_attempts(*, candidate: EvalAttemptResult, baseline: EvalAttemptResult | None) -> str | None:
    if baseline is None:
        return None
    if candidate.succeeded and not baseline.succeeded:
        return "candidate_better"
    if baseline.succeeded and not candidate.succeeded:
        return "candidate_worse"
    if candidate.schema_valid and not baseline.schema_valid:
        return "candidate_better"
    if baseline.schema_valid and not candidate.schema_valid:
        return "candidate_worse"
    return "unchanged"
