import type {
  AgentCanvasChatTurnV2,
  ConceptProposalV2,
  GuidedProductionJourneyV2,
  JourneyElementDecisionV2,
} from "../../../types-v2.ts";

/** Use persisted occurrence numbers, so retries and Main/Turnaround share a label. */
export function projectCharacterDesignerNumbers(
  proposals: readonly Pick<ConceptProposalV2,
    "capability_id" | "turn_id" | "occurrence_id" | "occurrence_index" | "occurrence_count" | "materialization">[],
  journey: GuidedProductionJourneyV2 | null | undefined,
  turns: Record<string, Pick<AgentCanvasChatTurnV2, "retry_of_turn_id">> = {},
): Map<string, number> {
  const occurrences = new Map((journey?.decisions ?? [])
    .filter(decision => decision.element_kind === "character")
    .map(decision => [decision.occurrence_id, decision.occurrence_index]));
  const numbers = new Map<string, number>();
  let characterCount = Math.max(occurrences.size, ...occurrences.values(), 0);
  for (const proposal of proposals) {
    if (proposal.capability_id !== "character_design") continue;
    const index = proposal.occurrence_index
      ?? (proposal.occurrence_id ? occurrences.get(proposal.occurrence_id) : undefined);
    characterCount = Math.max(characterCount, proposal.occurrence_count ?? 0, index ?? 0);
    if (!index) continue;
    if (proposal.occurrence_id) occurrences.set(proposal.occurrence_id, index);
    numbers.set(proposal.turn_id, index);
    if (proposal.materialization) numbers.set(proposal.materialization.turn_id, index);
  }
  if (characterCount <= 1) return new Map();

  for (const action of [journey?.active_action, journey?.suspended_action]) {
    if (action?.stage !== "character" || !action.turn_id || !action.occurrence_id) continue;
    const index = occurrences.get(action.occurrence_id);
    if (index) numbers.set(action.turn_id, index);
  }
  for (const [turnId, turn] of Object.entries(turns)) {
    if (numbers.has(turnId)) continue;
    const visited = new Set([turnId]);
    let source = turn.retry_of_turn_id;
    while (source && !visited.has(source)) {
      const index = numbers.get(source);
      if (index) {
        numbers.set(turnId, index);
        break;
      }
      visited.add(source);
      source = turns[source]?.retry_of_turn_id ?? null;
    }
  }
  return numbers;
}

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
    item.occurrence_id === occurrenceId
    && (item.character_phase === phase || (item.character_phase === null && item.evidence_kind === "stage_failed"))
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
