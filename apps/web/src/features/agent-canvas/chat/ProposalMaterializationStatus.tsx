import type { ProposalMaterializationProjectionV2 } from "../../../types-v2.ts";

const STATUS_COPY: Record<ProposalMaterializationProjectionV2["status"], string> = {
  queued: "Preparing the selected direction",
  working: "Creating Draft nodes and bindings",
  completed: "Draft creation completed",
  failed: "Draft creation failed",
};

export function ProposalMaterializationStatus({
  materialization,
}: {
  materialization: ProposalMaterializationProjectionV2;
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
          <small>{materialization.error.message}</small>
        ) : null}
        {materialization.status === "failed" && materialization.retryable ? (
          <small>You can retry with the selected direction and references.</small>
        ) : null}
      </div>
    </div>
  );
}
