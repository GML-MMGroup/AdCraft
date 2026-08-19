import type { GuidanceAdvancePreconditionV1 } from "../../../types-v2.ts";

/**
 * The backend resolves exact replays by this logical identity. A new authority
 * snapshot is intentionally a new command, never a replay of stale input.
 */
export function guidanceAdvanceIdempotencyKey(
  workflowId: string,
  authorityDigest: string,
): string {
  return `guidance-advance:${workflowId}:${authorityDigest}`;
}

export function mayRebaseGuidanceAdvance(
  stale: GuidanceAdvancePreconditionV1,
  refreshed: GuidanceAdvancePreconditionV1 | null,
): refreshed is GuidanceAdvancePreconditionV1 {
  return Boolean(
    refreshed
    && refreshed.session_id === stale.session_id
    && refreshed.session_status === "active"
    && refreshed.journey_stage !== "completed"
    && refreshed.authority_digest !== stale.authority_digest,
  );
}
