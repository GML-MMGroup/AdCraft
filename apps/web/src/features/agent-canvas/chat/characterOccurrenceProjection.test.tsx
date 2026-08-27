import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GuidedProductionJourneyV2, JourneyElementDecisionV2 } from "../../../types-v2.ts";
import { CharacterOccurrenceProgress } from "./CharacterOccurrenceProgress.tsx";
import { projectCharacterOccurrences } from "./characterOccurrenceProjection.ts";

function decision(
  occurrenceIndex: number,
  requirements: Record<string, unknown>,
): JourneyElementDecisionV2 {
  return {
    decision_id: `decision:character:${occurrenceIndex}`,
    element_kind: "character",
    occurrence_id: `occurrence:character:${occurrenceIndex}`,
    occurrence_index: occurrenceIndex,
    outcome: "include",
    source: "user",
    source_revision: 1,
    requirements,
  };
}

function journey(decisions: JourneyElementDecisionV2[]): GuidedProductionJourneyV2 {
  return {
    policy_version: "fixed_ad_production_v2",
    stage: "character",
    stage_status: "waiting_user",
    stage_revision: 5,
    decisions,
    active_occurrence_id: "occurrence:character:1",
    active_action: null,
    suspended_action: null,
    transition_evidence: [],
  };
}

describe("projectCharacterOccurrences", () => {
  it("returns no inferred Character when the journey has zero Character occurrences", () => {
    expect(projectCharacterOccurrences(journey([]))).toEqual([]);
  });

  it("projects one Character from persisted requirement data", () => {
    expect(projectCharacterOccurrences(journey([
      decision(1, { role: "Lead", identity_summary: "A precise studio director" }),
    ]))).toEqual([{
      occurrenceId: "occurrence:character:1",
      occurrenceIndex: 1,
      label: "Lead",
      summary: "A precise studio director",
      outcome: "include",
      active: true,
    }]);
  });

  it("sorts and renders multiple persisted Character occurrences without a fixed count", () => {
    const value = journey([
      decision(2, { role: "Supporting", identity_summary: "A product specialist" }),
      decision(1, { role: "Lead", identity_summary: "A studio director" }),
    ]);

    render(<CharacterOccurrenceProgress journey={value} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getAllByTestId("character-occurrence").map((node) => node.textContent)).toEqual([
      "LeadA studio director",
      "SupportingA product specialist",
    ]);
  });
});
