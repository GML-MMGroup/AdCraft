import { describe, expect, it } from "vitest";

import { agentCanvasChatErrorMessage } from "./chatErrorMessage.ts";

describe("agentCanvasChatErrorMessage", () => {
  it("preserves precise contract and persistence error codes", () => {
    expect(agentCanvasChatErrorMessage(
      "proposal_persistence_failed",
      "The proposal could not be stored.",
    )).toBe("proposal_persistence_failed: The proposal could not be stored.");
  });

  it("keeps agent_runtime_unavailable limited to its transport message", () => {
    expect(agentCanvasChatErrorMessage("agent_runtime_unavailable", null)).toBe(
      "agent_runtime_unavailable: The agent runtime is temporarily unavailable. Your input is preserved; try again shortly.",
    );
  });
});
