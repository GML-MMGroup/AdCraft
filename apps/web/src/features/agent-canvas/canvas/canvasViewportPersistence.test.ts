import { describe, expect, it } from "vitest";

import { shouldPersistAgentCanvasViewport } from "./canvasViewportPersistence.ts";

describe("shouldPersistAgentCanvasViewport", () => {
  it("does not persist the temporary fit viewport during layout preview", () => {
    expect(shouldPersistAgentCanvasViewport({
      focusedNodeId: null,
      layoutPreviewActive: true,
    })).toBe(false);
  });

  it("persists ordinary canvas movement only outside focus and layout preview", () => {
    expect(shouldPersistAgentCanvasViewport({
      focusedNodeId: null,
      layoutPreviewActive: false,
    })).toBe(true);
    expect(shouldPersistAgentCanvasViewport({
      focusedNodeId: "node-1",
      layoutPreviewActive: false,
    })).toBe(false);
  });
});
