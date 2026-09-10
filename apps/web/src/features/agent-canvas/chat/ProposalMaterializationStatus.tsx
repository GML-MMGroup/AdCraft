import type { ProposalMaterializationProjectionV2 } from "../../../types-v2.ts";
import { canRetryFailureInScope, failureUserAction } from "./actionableFailure.ts";

const STATUS_COPY: Record<ProposalMaterializationProjectionV2["status"], string> = {
  queued: "Preparing the selected direction",
  working: "Creating Draft nodes and bindings",
  completed: "Draft creation completed",
  failed: "Draft creation failed",
};

export function ProposalMaterializationStatus({
  materialization,
  retrying = false,
  onRetry,
  onRecover,
}: {
  materialization: ProposalMaterializationProjectionV2;
  retrying?: boolean;
  onRetry?: (turnId: string) => Promise<boolean>;
  onRecover?: (action: "revise" | "redesign") => void;
}) {
  const userAction = failureUserAction(materialization.error?.actionable_failure);
  const canRetry = canRetryFailureInScope(
    materialization.error?.actionable_failure,
    "turn",
  );
  return (
    <div
      className={`agent-chat__proposal-materialization is-${materialization.status}`}
      role="status"
      aria-label={`Proposal materialization ${materialization.status}`}
    >
      <span aria-hidden="true" />
      <div>
        <strong>{STATUS_COPY[materialization.status]}</strong>
        {materialization.status === "failed" && materialization.error ? (
          <small>
            {materialization.error.message}
            <span className="agent-chat__proposal-error-code">{materialization.error.code}</span>
          </small>
        ) : null}
        {materialization.status === "failed" && canRetry ? (
          <>
            <small>You can retry with the selected direction and references.</small>
            {onRetry ? (
              <button
                type="button"
                aria-label="Retry draft creation"
                disabled={retrying}
                onClick={() => void onRetry(materialization.turn_id)}
              >
                {retrying ? "Retrying..." : "Retry"}
              </button>
            ) : null}
          </>
        ) : null}
        {materialization.status === "failed"
          && (userAction === "revise" || userAction === "redesign")
          && onRecover ? (
            <button
              type="button"
              aria-label={userAction === "redesign" ? "Redesign proposal" : "Revise proposal"}
              onClick={() => onRecover(userAction)}
            >
              {userAction === "redesign" ? "Redesign" : "Revise"}
            </button>
          ) : null}
      </div>
    </div>
  );
}
