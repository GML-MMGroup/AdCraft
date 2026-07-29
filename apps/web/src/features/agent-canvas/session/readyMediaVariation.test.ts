import { describe, expect, it } from "vitest";

import type { CanvasNodeTypeV2, CanvasNodeV2 } from "../../../types-v2.ts";
import {
  readyMediaSiblingRequest,
  readyMediaVariationFromNode,
} from "./readyMediaVariation.ts";

function readyMediaNode(nodeType: CanvasNodeTypeV2 = "image"): CanvasNodeV2 {
  return {
    node_id: `${nodeType}-source`,
    workflow_id: "workflow-1",
    node_type: nodeType,
    semantic_role: `${nodeType}_hero`,
    role_contract_version: "ad-media-role-v1",
    title: `${nodeType} source`,
    status: "ready",
    summary_prompt: `Summary for ${nodeType}`,
    generation_prompt: `Generate ${nodeType}`,
    structured_content: { nested: { treatment: "premium" } },
    model_id: `${nodeType}-model-v1`,
    parameters: { aspect_ratio: "16:9", nested: { strength: 0.8 } },
    prompt_context_snapshot_id: "snapshot-1",
    output_asset_id: `${nodeType}-asset`,
    video_skill_run_id: nodeType === "video" ? "video-skill-1" : null,
    position: { x: 640, y: 240 },
    revision: 4,
    error: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

describe("Ready media variation request", () => {
  it.each(["image", "video", "audio"] as const)(
    "builds an edited %s sibling without mutating or referencing the source output",
    (nodeType) => {
      const source = readyMediaNode(nodeType);
      const sourceSnapshot = structuredClone(source);
      const request = readyMediaSiblingRequest(source, {
        title: "Alternative hero",
        generationPrompt: "A cleaner premium alternative.",
        modelId: `${nodeType}-model-v2`,
        parameters: { aspect_ratio: "3:4", nested: { strength: 0.4 } },
      });

      expect(request).toEqual({
        node_type: nodeType,
        semantic_role: source.semantic_role,
        role_contract_version: "ad-media-role-v1",
        title: "Alternative hero",
        summary_prompt: source.summary_prompt,
        generation_prompt: "A cleaner premium alternative.",
        structured_content: source.structured_content,
        model_id: `${nodeType}-model-v2`,
        parameters: { aspect_ratio: "3:4", nested: { strength: 0.4 } },
        position: { x: 704, y: 296 },
        clone_inputs_from_node_id: source.node_id,
        video_skill_run_id: source.video_skill_run_id,
      });
      expect(request).not.toHaveProperty("source_asset_id");
      expect(source).toEqual(sourceSnapshot);

      (request.structured_content!.nested as { treatment: string }).treatment = "changed";
      (request.parameters!.nested as { strength: number }).strength = 1;
      expect(source).toEqual(sourceSnapshot);
    },
  );

  it("initializes a defensive variation draft from the canonical source", () => {
    const source = readyMediaNode();
    const draft = readyMediaVariationFromNode(source);

    expect(draft).toEqual({
      title: "image source",
      generationPrompt: "Generate image",
      modelId: "image-model-v1",
      parameters: { aspect_ratio: "16:9", nested: { strength: 0.8 } },
    });

    (draft.parameters.nested as { strength: number }).strength = 0.1;
    expect((source.parameters.nested as { strength: number }).strength).toBe(0.8);
  });

  it("rejects Draft and unsupported Ready source nodes", () => {
    expect(() => readyMediaSiblingRequest(
      { ...readyMediaNode(), status: "draft" },
      readyMediaVariationFromNode(readyMediaNode()),
    )).toThrow("Only Ready Image, Video, or Audio nodes can generate variations.");

    expect(() => readyMediaSiblingRequest(
      readyMediaNode("text"),
      readyMediaVariationFromNode(readyMediaNode("text")),
    )).toThrow("Only Ready Image, Video, or Audio nodes can generate variations.");
  });
});
