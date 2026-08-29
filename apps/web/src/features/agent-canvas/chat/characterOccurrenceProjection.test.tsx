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

function characterEvidence(
  occurrenceIndex: number,
  characterPhase: "main" | "turnaround",
): GuidedProductionJourneyV2["transition_evidence"][number] {
  return {
    evidence_id: `evidence:character:${occurrenceIndex}:${characterPhase}`,
    evidence_kind: "targeted_action_finished",
    source_id: `node-character-${occurrenceIndex}-${characterPhase}`,
    source_revision: 1,
    stage: "character",
    stage_revision: 5,
    occurrence_id: `occurrence:character:${occurrenceIndex}`,
    character_phase: characterPhase,
    actor: "system",
    recorded_at: "2026-08-27T08:00:00Z",
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
      phases: { main: "awaiting-user", turnaround: "awaiting-user" },
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
      "LeadA studio directorCharacter MainCharacter Turnaround",
      "SupportingA product specialistCharacter MainCharacter Turnaround",
    ]);
  });

  it("projects Main and Turnaround independently from authoritative occurrence evidence", () => {
    const value = journey([decision(1, { role: "Lead" })]);
    value.transition_evidence = [characterEvidence(1, "main")];
    value.active_action = {
      action_id: "action-character-1-turnaround",
      action_kind: "prepare_character_turnaround",
      stage: "character",
      stage_revision: 5,
      status: "working",
      turn_id: "turn-character-1",
      occurrence_id: "occurrence:character:1",
      character_phase: "turnaround",
    };

    const projected = projectCharacterOccurrences(value);
    expect(projected[0]?.phases).toEqual({
      main: "ready",
      turnaround: "working",
    });

    render(<CharacterOccurrenceProgress journey={value} />);
    expect(screen.getAllByTestId("character-phase-main").at(-1)?.getAttribute("data-status")).toBe("ready");
    expect(screen.getAllByTestId("character-phase-turnaround").at(-1)?.getAttribute("data-status")).toBe("working");
  });

  it.each([
    ["reserved", "queued"],
    ["working", "working"],
    ["waiting_user", "awaiting-user"],
  ] as const)("maps an active action status %s to %s", (actionStatus, expected) => {
    const value = journey([decision(1, { role: "Lead" })]);
    value.active_action = {
      action_id: `action-${actionStatus}`,
      action_kind: "prepare_character_main",
      stage: "character",
      stage_revision: 5,
      status: actionStatus,
      turn_id: "turn-character-1",
      occurrence_id: "occurrence:character:1",
      character_phase: "main",
    };

    expect(projectCharacterOccurrences(value)[0]?.phases.main).toBe(expected);
  });

  it("maps stage failures to blocked and terminal evidence to ready", () => {
    const value = journey([decision(1, { role: "Lead" })]);
    value.stage_status = "failed";
    expect(projectCharacterOccurrences(value)[0]?.phases).toEqual({
      main: "blocked",
      turnaround: "blocked",
    });

    value.stage_status = "working";
    value.transition_evidence = [characterEvidence(1, "main")];
    expect(projectCharacterOccurrences(value)[0]?.phases).toEqual({
      main: "ready",
      turnaround: "queued",
    });
  });
});
