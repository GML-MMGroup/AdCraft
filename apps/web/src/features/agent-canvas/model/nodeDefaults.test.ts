import { describe, expect, it } from "vitest";

import {
  createDefaultCanvasNodeRequest,
  sourceAssetSemanticRole,
  sourceAssetStructuredContent,
} from "./nodeDefaults.ts";

describe("Agent Canvas node defaults", () => {
  it.each([
    ["text", "general_text"],
    ["script", "script"],
    ["image", "general_image"],
    ["video", "general_video"],
    ["audio", "bgm"],
    ["editing", "editing"],
  ] as const)("uses the frozen creative role for %s nodes", (nodeType, creativeRole) => {
    expect(createDefaultCanvasNodeRequest(nodeType, { x: 10, y: 20 })).toMatchObject({
      node_type: nodeType,
      creative_role: creativeRole,
      role_contract_version: "ad-media-role-v1",
      position: { x: 10, y: 20 },
    });
  });

  it("uses uploaded roles for source media nodes", () => {
    expect(sourceAssetSemanticRole("image")).toBe("general_image");
    expect(sourceAssetSemanticRole("video")).toBe("general_video");
    expect(sourceAssetSemanticRole("audio")).toBe("general_audio");
  });

  it("provides a valid BGM contract for blank and imported audio nodes", () => {
    expect(createDefaultCanvasNodeRequest("audio", { x: 0, y: 0 }).structured_content)
      .toMatchObject({
        duration_seconds: 30,
        instrumental_only: true,
        no_vocals: true,
      });
    expect(sourceAssetStructuredContent("audio", "Imported score", 18)).toMatchObject({
      music_summary: "Imported score",
      duration_seconds: 18,
    });
  });

  it("creates an empty Script as a runnable draft instead of a completed document", () => {
    const request = createDefaultCanvasNodeRequest("script", { x: 0, y: 0 });

    expect(request.generation_prompt).toBe("");
    expect(request.structured_content).toBeUndefined();
  });
});
