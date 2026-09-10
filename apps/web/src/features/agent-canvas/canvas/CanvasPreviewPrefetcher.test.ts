import { describe, expect, it } from "vitest";

import { canvasPreviewCandidates } from "./canvasPreviewPrefetchModel.ts";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";

function node(id: string, nodeType: "image" | "video", x: number, assetPath: string): AgentCanvasFlowNode {
  return {
    id,
    type: "agentCanvas",
    position: { x, y: 0 },
    data: {
      node: { node_id: id, node_type: nodeType } as AgentCanvasFlowNode["data"]["node"],
      asset: {
        asset_id: `asset-${id}`,
        version_id: `version-${id}`,
        preview_url: assetPath,
        poster_url: nodeType === "video" ? assetPath : null,
      },
    },
  };
}

describe("canvasPreviewCandidates", () => {
  it("prefetches derived previews near the viewport and excludes source content", () => {
    const candidates = canvasPreviewCandidates([
      node("near", "image", 650, "/api/v2/assets/a/preview?size=640"),
      node("idle", "video", 1_400, "/api/v2/assets/v/poster?size=640"),
      node("far", "image", 8_000, "/api/v2/assets/f/content"),
    ], { x: 0, y: 0, zoom: 1 }, 600, 400);

    expect(candidates.map((item) => item.priority)).toEqual(["warm", "idle"]);
    expect(candidates.every((item) => !item.url.endsWith("/content"))).toBe(true);
  });
});
