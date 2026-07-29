import type {
  CanvasNodeCreateRequestV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";

export type ReadyMediaVariationDraft = {
  title: string;
  generationPrompt: string;
  modelId: string | null;
  parameters: CanvasNodeV2["parameters"];
};

export function readyMediaVariationFromNode(
  source: CanvasNodeV2,
): ReadyMediaVariationDraft {
  return {
    title: source.title,
    generationPrompt: source.generation_prompt ?? "",
    modelId: source.model_id,
    parameters: structuredClone(source.parameters),
  };
}

export function readyMediaSiblingRequest(
  source: CanvasNodeV2,
  draft: ReadyMediaVariationDraft,
): CanvasNodeCreateRequestV2 {
  if (
    source.status !== "ready"
    || !["image", "video", "audio"].includes(source.node_type)
  ) {
    throw new Error("Only Ready Image, Video, or Audio nodes can generate variations.");
  }

  return {
    node_type: source.node_type,
    semantic_role: source.semantic_role,
    role_contract_version: source.role_contract_version,
    title: draft.title.trim() || source.title,
    summary_prompt: source.summary_prompt,
    generation_prompt: draft.generationPrompt,
    structured_content: structuredClone(source.structured_content),
    model_id: draft.modelId,
    parameters: structuredClone(draft.parameters),
    position: {
      x: source.position.x + 64,
      y: source.position.y + 56,
    },
    clone_inputs_from_node_id: source.node_id,
    video_skill_run_id: source.video_skill_run_id,
  };
}
