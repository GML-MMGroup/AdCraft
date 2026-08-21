import { describe, expect, it } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import {
  guidedInteractionContentVersion,
  shouldRenderStandaloneInteraction,
} from "./guidedInteractionPlacement.ts";

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "concept_choice",
  status: "open",
  response_locale: "en",
  expected_session_revision: 8,
  revision: 3,
  title: "Choose a direction",
  context: "Choose one direction to continue.",
  content: { content_kind: "concept_choice", proposal_id: "proposal-1", options: [] },
  allowed_actions: ["select", "revise", "delegate"],
  submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-1/submit",
  created_at: "2026-08-17T00:00:00Z",
  updated_at: "2026-08-17T00:00:00Z",
};

describe("guided interaction placement", () => {
  it("keeps the current interaction standalone even when Timeline contains its proposal", () => {
    expect(shouldRenderStandaloneInteraction(interaction)).toBe(true);
  });

  it("keeps non-proposal interactions in the standalone interaction area", () => {
    const questionnaire: GuidedInteractionV1 = {
      ...interaction,
      kind: "decision_bundle",
      content: { content_kind: "questionnaire", questions: [] },
    };

    expect(shouldRenderStandaloneInteraction(questionnaire)).toBe(true);
  });

  it("does not pin interactions that are no longer open", () => {
    expect(shouldRenderStandaloneInteraction({
      ...interaction,
      status: "submitted",
    })).toBe(false);
  });

  it("changes the timeline content version when the active review changes", () => {
    expect(guidedInteractionContentVersion(interaction)).toBe("interaction-1:3:open");
    expect(guidedInteractionContentVersion({
      ...interaction,
      revision: 4,
      status: "submitted",
    })).toBe("interaction-1:4:submitted");
    expect(guidedInteractionContentVersion(null)).toBe("");
  });
});
