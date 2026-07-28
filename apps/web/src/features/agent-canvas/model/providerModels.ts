import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";

type ProviderInputType = "text" | "image" | "video" | "audio";

export function providerInputTypes(
  workflow: AgentCanvasWorkflowV2,
  targetNodeId: string,
): ProviderInputType[] {
  const inputTypes = new Set<ProviderInputType>(["text"]);
  workflow.bindings
    .filter((binding) => binding.target_node_id === targetNodeId)
    .forEach((binding) => {
      const sourceRef = binding.source;
      if (sourceRef.kind === "image_asset") {
        inputTypes.add("image");
        return;
      }
      const source = workflow.nodes.find((node) => node.node_id === sourceRef.node_id);
      if (!source) return;
      if (source.node_type === "text" || source.node_type === "script") {
        inputTypes.add("text");
      } else if (source.node_type === "editing") {
        inputTypes.add("video");
      } else {
        inputTypes.add(source.node_type);
      }
    });
  return Array.from(inputTypes).sort();
}

export function usesMediaProvider(node: CanvasNodeV2 | null): node is CanvasNodeV2 {
  return Boolean(node && ["image", "video", "audio"].includes(node.node_type));
}
