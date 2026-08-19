import type { ProposalMaterializationProjectionV2 } from "../../../types-v2.ts";

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
}: {
  materialization: ProposalMaterializationProjectionV2;
  retrying?: boolean;
  onRetry?: (turnId: string) => Promise<boolean>;
}) {
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
        {materialization.status === "failed" && materialization.retryable ? (
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
      </div>
    </div>
  );
}
