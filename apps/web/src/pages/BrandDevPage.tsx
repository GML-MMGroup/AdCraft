import { useCallback, useState } from "react";
import { v2Api } from "../api/v2Client.ts";
import { BrandDecisionPanel } from "../features/agent-canvas/brand/BrandDecisionPanel.tsx";
import type {
  BrandDecisionLogEntryV1,
  BrandDecisionPanelV1,
  BrandInspectionConversationTurnV1,
} from "../features/agent-canvas/brand/brandDecisions.ts";
import "./brand-dev.css";

type LoadedState = {
  workflowId: string;
  decisions: BrandDecisionPanelV1 | null;
  conversation: BrandInspectionConversationTurnV1[];
  decisionLog: BrandDecisionLogEntryV1[];
  traces: unknown[];
};

export function BrandDevPage() {
  const [workflowId, setWorkflowId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<LoadedState | null>(null);

  const load = useCallback(async (id: string) => {
    const trimmed = id.trim();
    if (!trimmed) {
      setError("Enter a workflow id.");
      return;
    }
    setLoading(true);
    setError(null);
    const [decisions, conversation, decisionLog, traces] = await Promise.allSettled([
      v2Api.brandDecisions(trimmed),
      v2Api.brandInspectionConversation(trimmed),
      v2Api.brandInspectionDecisionLog(trimmed),
      v2Api.brandInspectionTraces(trimmed),
    ]);
    setLoading(false);
    if (decisions.status === "rejected" && conversation.status === "rejected") {
      setError("No brand data found for this workflow.");
      setState(null);
      return;
    }
    setState({
      workflowId: trimmed,
      decisions: decisions.status === "fulfilled" ? decisions.value : null,
      conversation: conversation.status === "fulfilled" ? conversation.value : [],
      decisionLog: decisionLog.status === "fulfilled" ? decisionLog.value : [],
      traces: traces.status === "fulfilled" ? traces.value : [],
    });
  }, []);

  return (
    <section className="content-wrap brand-dev-page">
      <h1>Brand professional mode inspection</h1>
      <p className="brand-dev-page__hint">
        Read-only view of the brand decision pipeline. Paste a workflow id to inspect.
      </p>
      <form
        className="brand-dev-page__form"
        onSubmit={(event) => {
          event.preventDefault();
          void load(workflowId);
        }}
      >
        <input
          value={workflowId}
          onChange={(event) => setWorkflowId(event.target.value)}
          placeholder="adwf_v2_..."
          aria-label="Workflow id"
        />
        <button type="submit" disabled={loading}>
          {loading ? "Loading…" : "Load"}
        </button>
      </form>
      {error ? <p className="brand-dev-page__error" role="alert">{error}</p> : null}
      {state ? (
        <div className="brand-dev-page__content">
          {state.decisions ? (
            <div className="brand-dev-page__panel">
              <BrandDecisionPanel
                decisions={state.decisions}
                refreshing={loading}
                interactive={false}
                onRefresh={() => {
                  void load(state.workflowId);
                }}
              />
            </div>
          ) : (
            <p className="brand-dev-page__hint">No decision panel data for this workflow.</p>
          )}
          <div className="brand-dev-page__tables">
            <h2>Conversation turns</h2>
            <table>
              <thead>
                <tr>
                  <th>Turn</th>
                  <th>Role</th>
                  <th>Text</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {state.conversation.map((turn) => (
                  <tr key={turn.turn_id}>
                    <td>{turn.turn_id}</td>
                    <td>{turn.role}</td>
                    <td>{turn.text}</td>
                    <td>{turn.status ?? "—"}{turn.error_code ? ` (${turn.error_code})` : ""}</td>
                    <td>{turn.created_at ?? "—"}</td>
                  </tr>
                ))}
                {state.conversation.length === 0 ? (
                  <tr><td colSpan={5}>No conversation turns.</td></tr>
                ) : null}
              </tbody>
            </table>
            <h2>Decision log</h2>
            <table>
              <thead>
                <tr>
                  <th>Log</th>
                  <th>Stage</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {state.decisionLog.map((entry) => (
                  <tr key={entry.log_id}>
                    <td>{entry.log_id}</td>
                    <td>{entry.stage}</td>
                    <td>{entry.action}</td>
                    <td>{entry.target_type}{entry.target_id ? ` · ${entry.target_id}` : ""}</td>
                    <td>{entry.created_at ?? "—"}</td>
                  </tr>
                ))}
                {state.decisionLog.length === 0 ? (
                  <tr><td colSpan={5}>No decision log entries.</td></tr>
                ) : null}
              </tbody>
            </table>
            <h2>Model traces</h2>
            <pre>{state.traces.length > 0 ? JSON.stringify(state.traces, null, 2) : "No traces."}</pre>
          </div>
        </div>
      ) : null}
    </section>
  );
}
