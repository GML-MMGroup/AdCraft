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

  it("explains historical Requirement Ledger gaps without masking their backend codes", () => {
    expect(agentCanvasChatErrorMessage("requirement_ledger_not_found", null)).toBe(
      "requirement_ledger_not_found: This older project is missing its Requirement Ledger. Its conversation cannot be restored until the project data is repaired.",
    );
    expect(agentCanvasChatErrorMessage("requirement_persistence_failed", null)).toBe(
      "requirement_persistence_failed: This project's Requirement Ledger does not match its saved snapshot. Backend data repair is required before the conversation can be restored.",
    );
  });
});
