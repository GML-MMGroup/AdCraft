import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { ConceptChoiceDecisionDock } from "./ConceptChoiceDecisionDock.tsx";

function interaction(context: string): GuidedInteractionV1 {
  return {
    interaction_id: "interaction-1",
    workflow_id: "workflow-1",
    kind: "concept_choice",
    status: "open",
    revision: 1,
    title: "A / B",
    context,
    content: {
      content_kind: "concept_choice",
      proposal_id: "proposal-1",
      stage: "product",
      stage_revision: 1,
      action_id: "action-1",
      occurrence_id: null,
      capability_id: "prop_design",
      options: [{ option_id: "option-a", title: "Unlock terminal", summary: "Summary", recommended: true }],
      allow_custom: true,
      allow_exclusion: false,
    },
  } as unknown as GuidedInteractionV1;
}

describe("ConceptChoiceDecisionDock title", () => {
  const props = { pending: false, issue: null, selectedOptionId: null, onSelectOption: () => undefined };

  it("keeps a user-facing context as the heading", () => {
    render(<ConceptChoiceDecisionDock {...props} interaction={interaction("Which hypothesis should lead this ad?")} roleName="Prop Designer" />);

    expect(screen.getByRole("article", { name: "Which hypothesis should lead this ad?" })).toBeTruthy();
  });

  it("replaces an internal purpose with the role heading", () => {
    const purpose = `Create the reviewed advertisement for Drumsticks. Preserve Treatment ${"a1".repeat(32)}.`;
    const { rerender } = render(<ConceptChoiceDecisionDock {...props} interaction={interaction(purpose)} roleName="Prop Designer" />);

    expect(screen.getByRole("article", { name: "Prop Designer: choose a direction" })).toBeTruthy();
    expect(screen.queryByText(/Preserve Treatment/)).toBeNull();

    rerender(<ConceptChoiceDecisionDock {...props} interaction={interaction(purpose)} />);
    expect(screen.getByRole("article", { name: "Choose a direction" })).toBeTruthy();
  });
});
