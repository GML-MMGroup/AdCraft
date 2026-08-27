import type {
  GuidedProductionJourneyV2,
  JourneyElementDecisionV2,
} from "../../../types-v2.ts";

export interface CharacterOccurrenceView {
  occurrenceId: string;
  occurrenceIndex: number;
  label: string;
  summary: string | null;
  outcome: JourneyElementDecisionV2["outcome"];
  active: boolean;
}

function optionalRequirement(
  requirements: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const key of keys) {
    const value = requirements[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export function projectCharacterOccurrences(
  journey: GuidedProductionJourneyV2,
): CharacterOccurrenceView[] {
  return journey.decisions
    .filter((decision) => decision.element_kind === "character")
    .toSorted((left, right) => left.occurrence_index - right.occurrence_index)
    .map((decision) => ({
      occurrenceId: decision.occurrence_id,
      occurrenceIndex: decision.occurrence_index,
      label: optionalRequirement(decision.requirements, ["role", "display_name", "name"])
        ?? `Character ${decision.occurrence_index}`,
      summary: optionalRequirement(decision.requirements, ["identity_summary", "summary"]),
      outcome: decision.outcome,
      active: decision.occurrence_id === journey.active_occurrence_id,
    }));
}
