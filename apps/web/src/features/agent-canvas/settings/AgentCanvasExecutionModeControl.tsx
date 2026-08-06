import type { GuidedSessionStateV2 } from "../../../types-v2.ts";
import { useAgentCanvasExecutionSettings } from "./useAgentCanvasExecutionSettings.ts";
import "./agent-canvas-settings.css";

export function AgentCanvasExecutionModeControl({
  workflowId,
  guidanceMode,
  eventRevision,
}: {
  workflowId: string;
  guidanceMode: GuidedSessionStateV2["guidance_mode"] | null;
  eventRevision: number;
}) {
  const execution = useAgentCanvasExecutionSettings(workflowId, eventRevision);
  const disabled = execution.loading || execution.saving || !execution.settings;

  return (
    <div className="agent-execution-mode">
      <div className="agent-execution-mode__authority">
        <span>Guidance</span>
        <strong>
          {guidanceMode === "delegated"
            ? "Delegated"
            : guidanceMode === "collaborative"
              ? "Collaborative"
              : "Not started"}
        </strong>
      </div>
      <div className="agent-execution-mode__control">
        <span>Media</span>
        <div role="group" aria-label="Media execution mode">
          <button
            type="button"
            aria-label="Manual media execution"
            aria-pressed={execution.settings?.media_execution_mode === "manual"}
            disabled={disabled}
            onClick={() => void execution.setMode("manual")}
          >
            Manual
          </button>
          <button
            type="button"
            aria-label="Automatic media execution"
            aria-pressed={execution.settings?.media_execution_mode === "automatic"}
            disabled={disabled}
            onClick={() => void execution.setMode("automatic")}
          >
            Automatic
          </button>
        </div>
      </div>
      {execution.conflict ? (
        <div className="agent-execution-mode__conflict" role="alert">
          <span>{execution.conflict.message}</span>
          <button
            type="button"
            disabled={execution.saving}
            aria-label={`Retry ${execution.conflict.desiredMode === "automatic" ? "Automatic" : "Manual"}`}
            onClick={() => void execution.retryConflict()}
          >
            Retry
          </button>
          <button type="button" onClick={execution.dismissConflict}>Keep current</button>
        </div>
      ) : null}
      {execution.error ? (
        <span className="agent-execution-mode__error" role="alert">{execution.error}</span>
      ) : null}
    </div>
  );
}
