import type {
  GuidedProductionJourneyV2,
  JourneyElementDecisionV2,
} from "../../../types-v2.ts";

export type CharacterPhaseStatus = "queued" | "working" | "ready" | "blocked" | "awaiting-user";

export interface CharacterOccurrenceView {
  occurrenceId: string;
  occurrenceIndex: number;
  label: string;
  summary: string | null;
  outcome: JourneyElementDecisionV2["outcome"];
  active: boolean;
  phases: {
    main: CharacterPhaseStatus;
    turnaround: CharacterPhaseStatus;
  };
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

function phaseStatus(
  journey: GuidedProductionJourneyV2,
  occurrenceId: string,
  phase: "main" | "turnaround",
): CharacterPhaseStatus {
  const activeAction = journey.active_action;
  if (activeAction?.occurrence_id === occurrenceId && activeAction.character_phase === phase) {
    if (activeAction.status === "reserved") return "queued";
    if (activeAction.status === "waiting_user") return "awaiting-user";
    return "working";
  }
  const evidence = journey.transition_evidence.filter((item) => (
    item.occurrence_id === occurrenceId && item.character_phase === phase
  ));
  const latest = evidence.at(-1);
  if (latest?.evidence_kind === "stage_failed") return "blocked";
  if (latest?.evidence_kind === "targeted_action_started") return "working";
  if (latest && (
    latest.evidence_kind === "character_materialized"
    || latest.evidence_kind === "character_delegated"
    || latest.evidence_kind === "character_excluded"
    || latest.evidence_kind === "targeted_action_finished"
  )) return "ready";

  if (journey.stage_status === "failed" || journey.stage_status === "blocked_external") return "blocked";
  if (journey.stage_status === "waiting_user") return "awaiting-user";
  if (journey.stage_status === "working") return "queued";
  if (journey.stage_status === "completed") return "ready";
  return "queued";
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
      phases: {
        main: phaseStatus(journey, decision.occurrence_id, "main"),
        turnaround: phaseStatus(journey, decision.occurrence_id, "turnaround"),
      },
    }));
}
