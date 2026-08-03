import { describe, expect, it } from "vitest";

import { agentCanvasApi } from "./agentCanvasApi.ts";

describe("agentCanvasApi", () => {
  it("does not expose the retired V2 provider capability projection", () => {
    expect("agentCanvasProviderCapabilities" in agentCanvasApi).toBe(false);
  });
});
