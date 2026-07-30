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
