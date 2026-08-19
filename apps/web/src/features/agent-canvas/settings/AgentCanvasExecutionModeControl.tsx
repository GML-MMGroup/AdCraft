import { useAgentCanvasExecutionSettings } from "./useAgentCanvasExecutionSettings.ts";
import "./agent-canvas-settings.css";

export function AgentCanvasExecutionModeControl({
  workflowId,
  eventRevision,
}: {
  workflowId: string;
  eventRevision: number;
}) {
  const execution = useAgentCanvasExecutionSettings(workflowId, eventRevision);
  const disabled = execution.loading || execution.saving || !execution.settings;

  return (
    <div className="agent-execution-mode">
      <div className="agent-execution-mode__control">
        <span>Collaboration</span>
        <button
          type="button"
          role="switch"
          aria-label="Automatic media collaboration"
          aria-checked={execution.settings?.media_execution_mode === "automatic"}
          disabled={disabled}
          title="Allow future eligible media Drafts to run automatically"
          onClick={() => void execution.setMode(
            execution.settings?.media_execution_mode === "automatic" ? "manual" : "automatic",
          )}
        >
          <i aria-hidden="true" />
        </button>
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
