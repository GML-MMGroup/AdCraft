import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

export function normalizeProviderParameters(
  nodeType: CanvasNodeV2["node_type"],
  source: Record<string, unknown>,
): { parameters: Record<string, unknown>; migrated: boolean } {
  if (nodeType !== "video") return { parameters: source, migrated: false };
  const parameters = { ...source };
  const requestedDuration = parameters.requested_duration_seconds;
  const currentDuration = parameters.duration_seconds;
  if (
    typeof currentDuration !== "number"
    && typeof requestedDuration === "number"
    && Number.isInteger(requestedDuration)
    && requestedDuration > 0
  ) {
    parameters.duration_seconds = requestedDuration;
  }
  if (
    typeof parameters.duration_seconds === "number"
    && (!Number.isInteger(parameters.duration_seconds) || parameters.duration_seconds <= 0)
  ) {
    delete parameters.duration_seconds;
  }
  const migrated = (
    "requested_duration_seconds" in parameters
    || "effective_duration_seconds" in parameters
    || parameters.duration_seconds !== currentDuration
  );
  delete parameters.requested_duration_seconds;
  delete parameters.effective_duration_seconds;
  return { parameters, migrated };
}

export function runnableDraftParameterMigrations(
  workflow: AgentCanvasWorkflowV2,
): Array<{ node_id: string; parameters: Record<string, unknown> }> {
  return workflow.nodes.flatMap((node) => {
    if (node.status !== "draft" || node.node_type !== "video") return [];
    const normalized = normalizeProviderParameters(node.node_type, node.parameters);
    if (!normalized.migrated) return [];
    return [{
      node_id: node.node_id,
      parameters: normalized.parameters,
    }];
  });
}
