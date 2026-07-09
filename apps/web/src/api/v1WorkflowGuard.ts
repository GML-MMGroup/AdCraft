export function isV2WorkflowId(workflowId?: string | null): boolean {
  return typeof workflowId === "string" && workflowId.startsWith("adwf_v2_");
}

export function assertV1WorkflowId(workflowId: string, operation: string): void {
  if (isV2WorkflowId(workflowId)) {
    throw new Error(`Blocked V1 workflow API "${operation}" for V2 workflow ${workflowId}.`);
  }
}
