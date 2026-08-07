import { describe, expect, it } from "vitest";

import {
  UNKNOWN_IMAGE_NODE_SIZE,
  agentCanvasFocusedNodeSize,
  agentCanvasNodePlacementSize,
  agentCanvasNodeSize,
} from "./nodeGeometry.ts";

describe("agentCanvasNodeSize", () => {
  it("fits common image ratios into a clear bounded canvas area without changing their ratio", () => {
    expect(agentCanvasNodeSize("image", { width: 1920, height: 1080 })).toEqual({
      width: 360,
      height: 203,
    });
    expect(agentCanvasNodeSize("image", { width: 1080, height: 1920 })).toEqual({
      width: 203,
      height: 360,
    });
    expect(agentCanvasNodeSize("image", { width: 1024, height: 1024 })).toEqual({
      width: 310,
      height: 310,
    });
  });

  it("keeps non-image nodes and images without valid dimensions at the stable default size", () => {
    expect(agentCanvasNodeSize("video", { width: 1080, height: 1920 })).toEqual({
      width: 272,
      height: 184,
    });
    expect(agentCanvasNodeSize("image", { width: null, height: 0 })).toEqual({
      width: 272,
      height: 184,
    });
  });

  it("keeps extreme image ratios large enough to preserve usable controls without cropping media", () => {
    expect(agentCanvasNodeSize("image", { width: 10_000, height: 100 })).toEqual({
      width: 360,
      height: 128,
    });
    expect(agentCanvasNodeSize("image", { width: 100, height: 10_000 })).toEqual({
      width: 128,
      height: 360,
    });
  });

  it("reserves the maximum image footprint until intrinsic dimensions are available", () => {
    expect(agentCanvasNodePlacementSize("image", null)).toEqual(UNKNOWN_IMAGE_NODE_SIZE);
    expect(agentCanvasNodePlacementSize("image", { width: 1920, height: 1080 })).toEqual({
      width: 360,
      height: 203,
    });
  });

  it("expands focused nodes into a large bounded area while preserving media ratios", () => {
    expect(agentCanvasFocusedNodeSize("text", null)).toEqual({ width: 1040, height: 680 });
    expect(agentCanvasFocusedNodeSize("image", { width: 1920, height: 1080 })).toEqual({
      width: 1040,
      height: 585,
    });
    expect(agentCanvasFocusedNodeSize("video", { width: 1080, height: 1920 })).toEqual({
      width: 383,
      height: 680,
    });
  });
});
