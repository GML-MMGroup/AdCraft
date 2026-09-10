import type { AgentCanvasChatTurnV2 } from "../../../types-v2.ts";
import { canRetryFailureInScope, turnActionableFailure } from "./actionableFailure.ts";

export function FailedTurnBubble({
  turn,
  retrying,
  onRetry,
}: {
  turn: AgentCanvasChatTurnV2;
  retrying: boolean;
  onRetry: () => void;
}) {
  const detail = turn.error_message?.trim()
    || turn.operation_failure?.message.trim()
    || "The Agent could not complete this response.";
  const canRetry = canRetryFailureInScope(turnActionableFailure(turn), "turn");

  return (
    <section
      className="agent-chat__failed-turn"
      role="alert"
      aria-label="Agent response failed"
    >
      <strong>Agent response failed</strong>
      <p>{detail}</p>
      {canRetry ? (
        <button
          type="button"
          aria-label="Retry failed Agent response"
          disabled={retrying}
          onClick={onRetry}
        >
          {retrying ? "Retrying…" : "Retry"}
        </button>
      ) : null}
    </section>
  );
}
