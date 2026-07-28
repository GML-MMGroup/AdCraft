import { describe, expect, it } from "vitest";

import { AGENT_CANVAS_SSE_EVENT_TYPES } from "./eventTypes.ts";

describe("Agent Canvas SSE subscriptions", () => {
  it("subscribes to current and canonical chat, graph, runtime, and editing events", () => {
    expect(AGENT_CANVAS_SSE_EVENT_TYPES).toEqual(expect.arrayContaining([
      "chat_turn_queued",
      "concept_proposal_created",
      "concept_options_ready",
      "script_artifact_created",
      "binding_created",
      "binding_removed",
      "asset_published",
      "node_run_started",
      "editing_export_completed",
    ]));
  });
});
