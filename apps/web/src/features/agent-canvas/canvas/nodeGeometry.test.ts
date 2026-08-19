import { describe, expect, it } from "vitest";

import {
  DEFAULT_AGENT_CANVAS_NODE_SIZE,
  SCRIPT_AGENT_CANVAS_NODE_MAX_HEIGHT,
  UNKNOWN_IMAGE_NODE_SIZE,
  agentCanvasNodePlacementSize,
  agentCanvasNodeSize,
  scriptNodeHeightForContent,
} from "./nodeGeometry.ts";

describe("agentCanvasNodeSize", () => {
  it("starts Script cards at the same height as a newly created Text card", () => {
    expect(agentCanvasNodeSize("script")).toEqual({
      width: 248,
      height: DEFAULT_AGENT_CANVAS_NODE_SIZE.height,
    });
  });

  it("grows Script cards with content and caps them at the scrollable maximum", () => {
    expect(scriptNodeHeightForContent(40)).toBe(DEFAULT_AGENT_CANVAS_NODE_SIZE.height);
    expect(scriptNodeHeightForContent(260)).toBe(330);
    expect(scriptNodeHeightForContent(900)).toBe(SCRIPT_AGENT_CANVAS_NODE_MAX_HEIGHT);
  });

  it("reserves the maximum Script footprint when placing nearby nodes", () => {
    expect(agentCanvasNodePlacementSize("script")).toEqual({
      width: 248,
      height: SCRIPT_AGENT_CANVAS_NODE_MAX_HEIGHT,
    });
  });

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
});
