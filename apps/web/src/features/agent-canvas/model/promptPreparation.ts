import type { CanvasNodeV2, NodePromptPreparationV1 } from "../../../types-v2.ts";

export function promptPreparationForNode(node: CanvasNodeV2): NodePromptPreparationV1 | null {
  return node.prompt_preparation;
}

export function isNodePromptReady(node: CanvasNodeV2): boolean {
  const preparation = promptPreparationForNode(node);
  return preparation?.status === "ready"
    && Boolean(node.generation_prompt?.trim())
    && Boolean(preparation.prompt_digest?.trim());
}

export function hasPromptReadyDraft(nodes: CanvasNodeV2[]): boolean {
  return nodes.some((node) => (
    node.status === "draft"
    && ["text", "script", "image", "video", "audio"].includes(node.node_type)
    && isNodePromptReady(node)
  ));
}
