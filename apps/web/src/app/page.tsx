"use client";

import {
  Check,
  CircleAlert,
  Clock,
  Database,
  GitBranch,
  ListFilter,
  Play,
  RefreshCw,
  RotateCw,
  Search,
  ShieldCheck,
  Split,
  SquareArrowOutUpRight,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";

type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "resumed"
  | "succeeded"
  | "failed"
  | "cancelled";

type RunRecord = {
  id: string;
  project_id: string;
  workflow_version_id: string;
  triggered_by: string | null;
  status: RunStatus;
  input_payload: Record<string, unknown>;
  final_output: Record<string, unknown> | null;
  started_at: string | null;
  ended_at: string | null;
  latency_ms: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  created_at: string;
};

type TraceSpan = {
  id: string;
  span_type: string;
  name: string;
  status: string;
  span_id: string;
  parent_span_id: string | null;
  attributes: Record<string, unknown>;
  error: Record<string, unknown> | null;
  started_at: string;
};

type ToolCall = {
  id: string;
  tool_name: string;
  status: string;
  approval_required: boolean;
  approval_id: string | null;
  args: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
};

type Approval = {
  id: string;
  run_id: string;
  tool_call_id: string;
  approver_role: string;
  status: string;
  reason: string;
  proposed_effect: Record<string, unknown> | null;
  decided_by: string | null;
};

type Connector = {
  id: string;
  name: string;
  connector_type: string;
  auth_mode: string;
  scopes: string[];
  status: string;
};

type ToolDefinition = {
  id: string;
  connector_id: string;
  name: string;
  risk_level: string;
  is_mutating: boolean;
  description: string;
};

type Timeline = {
  run: RunRecord;
  trace_spans: TraceSpan[];
  tool_calls: ToolCall[];
  approvals: Approval[];
};

const statusLabels: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_approval: "Approval",
  resumed: "Resumed",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

function previewJson(value: unknown) {
  if (value == null) return "-";
  return JSON.stringify(value, null, 2);
}

function statusClass(status: string) {
  if (["succeeded", "executed", "approved", "ok", "active"].includes(status)) return "ok";
  if (["failed", "rejected", "error", "cancelled"].includes(status)) return "bad";
  if (["awaiting_approval", "pending", "in_progress", "running", "resumed"].includes(status)) return "wait";
  return "idle";
}

async function api<T>(path: string, actorUserId: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Actor-User-Id": actorUserId,
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export default function ConsolePage() {
  const [actorUserId, setActorUserId] = useState("00000000-0000-0000-0000-000000000001");
  const [projectId, setProjectId] = useState("");
  const [workflowSlug, setWorkflowSlug] = useState("support-ticket-resolution");
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedRunId = timeline?.run.id ?? runs[0]?.id ?? "";
  const pendingApprovals = useMemo(() => approvals.filter((approval) => approval.status === "pending"), [approvals]);

  const loadRuns = useCallback(async () => {
    if (!projectId) return;
    setBusy("runs");
    setError(null);
    try {
      const records = await api<RunRecord[]>(`/api/v1/projects/${projectId}/runs`, actorUserId);
      setRuns(records);
      if (records[0]) {
        const loaded = await api<Timeline>(`/api/v1/projects/${projectId}/runs/${records[0].id}/timeline`, actorUserId);
        setTimeline(loaded);
      } else {
        setTimeline(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load runs");
    } finally {
      setBusy(null);
    }
  }, [actorUserId, projectId]);

  const loadApprovals = useCallback(async () => {
    if (!projectId) return;
    setBusy("approvals");
    setError(null);
    try {
      setApprovals(await api<Approval[]>(`/api/v1/projects/${projectId}/approvals`, actorUserId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load approvals");
    } finally {
      setBusy(null);
    }
  }, [actorUserId, projectId]);

  const loadConnectors = useCallback(async () => {
    if (!projectId) return;
    setBusy("connectors");
    setError(null);
    try {
      const connectorRecords = await api<Connector[]>(`/api/v1/projects/${projectId}/connectors`, actorUserId);
      setConnectors(connectorRecords);
      const toolRecords = await Promise.all(
        connectorRecords.map((connector) =>
          api<ToolDefinition[]>(`/api/v1/projects/${projectId}/connectors/${connector.id}/tools`, actorUserId),
        ),
      );
      setTools(toolRecords.flat());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load connectors");
    } finally {
      setBusy(null);
    }
  }, [actorUserId, projectId]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadRuns(), loadApprovals(), loadConnectors()]);
  }, [loadApprovals, loadConnectors, loadRuns]);

  async function selectRun(runId: string) {
    setBusy(runId);
    setError(null);
    try {
      setTimeline(await api<Timeline>(`/api/v1/projects/${projectId}/runs/${runId}/timeline`, actorUserId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load timeline");
    } finally {
      setBusy(null);
    }
  }

  async function executeRun(runId: string) {
    setBusy("execute");
    setError(null);
    try {
      await api<RunRecord>(`/api/v1/projects/${projectId}/runs/${runId}/execute`, actorUserId, { method: "POST" });
      await refreshAll();
      await selectRun(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to execute run");
    } finally {
      setBusy(null);
    }
  }

  async function submitRun() {
    if (!projectId || !workflowSlug) return;
    setBusy("submit");
    setError(null);
    try {
      const run = await api<RunRecord>(`/api/v1/projects/${projectId}/workflows/${workflowSlug}/runs`, actorUserId, {
        method: "POST",
        body: JSON.stringify({
          input_payload: {
            ticket_id: `T-${Date.now().toString().slice(-5)}`,
            customer_id: "C-500",
            message: "I was charged twice and need a refund.",
          },
        }),
      });
      await loadRuns();
      await selectRun(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to submit run");
    } finally {
      setBusy(null);
    }
  }

  async function decideApproval(approvalId: string, status: "approved" | "rejected") {
    setBusy(approvalId);
    setError(null);
    try {
      await api<Approval>(`/api/v1/projects/${projectId}/approvals/${approvalId}/decide`, actorUserId, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await refreshAll();
      if (selectedRunId) await selectRun(selectedRunId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to decide approval");
    } finally {
      setBusy(null);
    }
  }

  async function seedSupportDemo() {
    setBusy("seed");
    setError(null);
    try {
      await api<ToolDefinition[]>(`/api/v1/projects/${projectId}/connectors/support-demo/seed`, actorUserId, {
        method: "POST",
      });
      await loadConnectors();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to seed tools");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>Agent Reliability Platform</h1>
          <div className="subline">
            <GitBranch size={15} /> Support operations control plane
          </div>
        </div>
        <div className="toolbar">
          <button className="iconButton" onClick={refreshAll} disabled={!projectId || busy != null} title="Refresh">
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      <section className="contextBar">
        <label>
          Actor
          <input value={actorUserId} onChange={(event) => setActorUserId(event.target.value)} />
        </label>
        <label>
          Project
          <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="project uuid" />
        </label>
        <label>
          Workflow
          <input value={workflowSlug} onChange={(event) => setWorkflowSlug(event.target.value)} />
        </label>
        <button onClick={loadRuns} disabled={!projectId || busy != null}>
          <Search size={16} /> Load
        </button>
        <button onClick={submitRun} disabled={!projectId || busy != null}>
          <Play size={16} /> Submit
        </button>
        <button onClick={seedSupportDemo} disabled={!projectId || busy != null}>
          <Database size={16} /> Seed
        </button>
      </section>

      {error ? (
        <div className="notice">
          <CircleAlert size={17} />
          {error}
        </div>
      ) : null}

      <section className="grid">
        <div className="panel runsPanel">
          <div className="panelHeader">
            <h2>Runs</h2>
            <span>{runs.length}</span>
          </div>
          <div className="runList">
            {runs.map((run) => (
              <button
                key={run.id}
                className={`runRow ${timeline?.run.id === run.id ? "selected" : ""}`}
                onClick={() => selectRun(run.id)}
              >
                <span className={`pill ${statusClass(run.status)}`}>{statusLabels[run.status] ?? run.status}</span>
                <span className="runId">{run.id}</span>
                <span className="runMeta">{new Date(run.created_at).toLocaleString()}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="panel timelinePanel">
          <div className="panelHeader">
            <h2>Timeline</h2>
            <div className="headerActions">
              <button
                className="iconButton"
                onClick={() => selectedRunId && executeRun(selectedRunId)}
                disabled={!selectedRunId || busy != null}
                title="Execute"
              >
                <RotateCw size={17} />
              </button>
              <span>{timeline?.trace_spans.length ?? 0}</span>
            </div>
          </div>

          {timeline ? (
            <div className="timeline">
              {timeline.trace_spans.map((span) => (
                <div className="spanRow" key={span.id}>
                  <span className={`dot ${statusClass(span.status)}`} />
                  <div>
                    <div className="spanTitle">
                      <span>{span.span_type}</span>
                      <code>{span.name}</code>
                    </div>
                    <pre>{previewJson(span.error ?? span.attributes)}</pre>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={<ListFilter size={22} />} label="No run selected" />
          )}
        </div>

        <div className="panel sidePanel">
          <div className="panelHeader">
            <h2>Approvals</h2>
            <span>{pendingApprovals.length}</span>
          </div>
          <div className="approvalList">
            {approvals.map((approval) => (
              <div className="approvalRow" key={approval.id}>
                <div>
                  <div className="approvalTitle">
                    <span className={`pill ${statusClass(approval.status)}`}>{approval.status}</span>
                    <strong>{approval.approver_role}</strong>
                  </div>
                  <p>{approval.reason}</p>
                </div>
                {approval.status === "pending" ? (
                  <div className="decisionButtons">
                    <button className="iconButton approve" onClick={() => decideApproval(approval.id, "approved")}>
                      <Check size={17} />
                    </button>
                    <button className="iconButton reject" onClick={() => decideApproval(approval.id, "rejected")}>
                      <X size={17} />
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="panel detailPanel">
          <div className="panelHeader">
            <h2>Run Detail</h2>
            <span>{timeline?.run.status ?? "-"}</span>
          </div>
          {timeline ? (
            <div className="detailGrid">
              <Metric label="Latency" value={timeline.run.latency_ms == null ? "-" : `${timeline.run.latency_ms} ms`} />
              <Metric label="Input" value={timeline.run.tokens_input?.toString() ?? "-"} />
              <Metric label="Output" value={timeline.run.tokens_output?.toString() ?? "-"} />
              <Metric label="Version" value={timeline.run.workflow_version_id.slice(0, 8)} />
              <pre className="jsonBlock">{previewJson(timeline.run.final_output ?? timeline.run.input_payload)}</pre>
            </div>
          ) : (
            <EmptyState icon={<Clock size={22} />} label="No detail" />
          )}
        </div>

        <div className="panel sidePanel">
          <div className="panelHeader">
            <h2>Tools</h2>
            <span>{tools.length}</span>
          </div>
          <div className="toolList">
            {connectors.map((connector) => (
              <div className="connectorRow" key={connector.id}>
                <div className="connectorTitle">
                  <ShieldCheck size={16} />
                  <strong>{connector.name}</strong>
                  <span className={`pill ${statusClass(connector.status)}`}>{connector.status}</span>
                </div>
                {tools
                  .filter((tool) => tool.connector_id === connector.id)
                  .map((tool) => (
                    <div className="toolRow" key={tool.id}>
                      <span>{tool.name}</span>
                      <span>{tool.risk_level}</span>
                      {tool.is_mutating ? <SquareArrowOutUpRight size={14} /> : <Split size={14} />}
                    </div>
                  ))}
              </div>
            ))}
          </div>
        </div>

        <div className="panel callsPanel">
          <div className="panelHeader">
            <h2>Tool Calls</h2>
            <span>{timeline?.tool_calls.length ?? 0}</span>
          </div>
          <div className="callList">
            {timeline?.tool_calls.map((call) => (
              <div className="callRow" key={call.id}>
                <div className="callTitle">
                  <strong>{call.tool_name}</strong>
                  <span className={`pill ${statusClass(call.status)}`}>{call.status}</span>
                </div>
                <pre>{previewJson(call.result ?? call.error ?? call.args)}</pre>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function EmptyState({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="empty">
      {icon}
      <span>{label}</span>
    </div>
  );
}
