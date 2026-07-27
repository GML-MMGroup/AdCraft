import { describe, expect, it } from "vitest";

import type { UploadedAsset } from "../../../types.ts";
import type { CanvasNode, WorkflowNodeData } from "../types.ts";
import { layoutNodes } from "./workflowCanvasModel.ts";

function imageAsset(id: string, width: number, height: number): UploadedAsset {
  return {
    asset_id: id,
    asset_type: "image",
    asset_role: "generated",
    filename: `${id}.png`,
    mime_type: "image/png",
    local_path: `/media/${id}.png`,
    metadata: { width, height },
  };
}

function imageNode(id: string, asset: UploadedAsset): CanvasNode {
  const data: WorkflowNodeData = {
    title: id,
    description: id,
    status: "completed",
    nodeType: "image-generation",
    kind: "image-generation",
    family: "Image",
    category: "Generation",
    contentPreview: "",
    outputCount: 1,
    previewAssets: [asset],
    inputPorts: [],
    outputPorts: [],
  };
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data,
  };
}

describe("workflow media layout dimensions", () => {
  it("uses preview aspect ratios when spacing media nodes in one column", () => {
    const portrait = imageNode("portrait", imageAsset("portrait", 900, 1600));
    const landscape = imageNode("landscape", imageAsset("landscape", 1600, 900));

    const [first, second] = layoutNodes([portrait, landscape], []);

    expect(first.position.y).toBe(90);
    expect(second.position.y - first.position.y).toBe(520);
  });

  it("reserves portrait-safe space for media without dimensions", () => {
    const videoAsset = {
      ...imageAsset("video", 0, 0),
      asset_type: "video" as const,
      mime_type: "video/mp4",
      metadata: {},
    };
    const first = imageNode("video", videoAsset);
    first.data.family = "Video";
    const second = imageNode("next", imageAsset("next", 1600, 900));

    const [positionedFirst, positionedSecond] = layoutNodes([first, second], []);

    expect(positionedSecond.position.y - positionedFirst.position.y).toBe(520);
  });

  it("uses the composite node footprint for entity-area layouts", () => {
    const first = imageNode("character", imageAsset("character", 1600, 900));
    first.data.kind = "character-generation";
    const second = imageNode("next", imageAsset("next", 1600, 900));

    const [positionedFirst, positionedSecond] = layoutNodes([first, second], []);

    expect(positionedSecond.position.y - positionedFirst.position.y).toBe(298);
  });
});
