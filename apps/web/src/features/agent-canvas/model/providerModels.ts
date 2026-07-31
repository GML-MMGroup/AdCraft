import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";

export type ProviderInputType = "text" | "image" | "video" | "audio";
export type ProviderOutputType = "image" | "video" | "audio";

const PROVIDER_OUTPUT_TYPES: ReadonlySet<CanvasNodeV2["node_type"]> = new Set([
  "image",
  "video",
  "audio",
]);

const INPUT_TYPE_BY_ROLE: Record<string, ProviderInputType> = {
  text_context: "text",
  brief_context: "text",
  script_context: "text",
  image_reference: "image",
  video_reference: "video",
  audio_reference: "audio",
};

function bindingInputType(binding: AgentCanvasWorkflowV2["bindings"][number]): ProviderInputType | null {
  return INPUT_TYPE_BY_ROLE[binding.input_role] ?? null;
}

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

export function providerInputTypes(
  workflow: AgentCanvasWorkflowV2,
  targetNodeId: string,
): ProviderInputType[] {
  const inputTypes = new Set<ProviderInputType>(["text"]);
  workflow.bindings
    .filter((binding) => binding.target_node_id === targetNodeId && binding.enabled)
    .forEach((binding) => {
      const inputType = bindingInputType(binding);
      if (inputType) inputTypes.add(inputType);
    });
  return Array.from(inputTypes).sort();
}

export function usesProvider(node: CanvasNodeV2 | null): node is CanvasNodeV2 {
  return Boolean(node && PROVIDER_OUTPUT_TYPES.has(node.node_type));
}

export function providerOutputType(node: CanvasNodeV2 | null): ProviderOutputType | null {
  if (!node || !PROVIDER_OUTPUT_TYPES.has(node.node_type)) return null;
  return node.node_type as ProviderOutputType;
}

export const usesMediaProvider = usesProvider;
