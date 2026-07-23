export type V2AuthoringConflictResolution = {
  target: { resource: "project" | "workflow"; id: string };
  operationPath: string;
  action: "retry" | "discard";
};

export function shouldCloseReferencePickerAfterAuthoringResolution(
  resolution: V2AuthoringConflictResolution | null | undefined,
  workflowId: string,
  slotId: string,
): boolean {
  return resolution?.target.resource === "workflow"
    && resolution.target.id === workflowId
    && resolution.operationPath === `/workflows/${encodeURIComponent(workflowId)}/slots/${encodeURIComponent(slotId)}/reference-selections`;
}
