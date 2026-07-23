import type { V2AuthoringResource } from "./v2EtagStore.ts";

export type V2AuthoringConflictTarget = {
  resource: V2AuthoringResource;
  id: string;
};

export const V2_AUTHORING_CONFLICT_RESOLVED_EVENT = "v2-authoring-conflict-resolved";
export const V2_AUTHORING_DRAFT_DISCARDED_EVENT = "v2-authoring-draft-discarded";

export type V2AuthoringConflictResolution = {
  target: V2AuthoringConflictTarget;
  operationPath: string;
  action: "retry" | "discard";
};
