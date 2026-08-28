import type { CanvasNodeV2 } from "../../../types-v2.ts";

export type CharacterNodePhase = "main" | "turnaround";

export interface CharacterNodePresentation {
  occurrenceId: string | null;
  phase: CharacterNodePhase;
  phaseLabel: "Character Main" | "Character Turnaround";
}

function phaseFromRoleVariant(value: string | null): CharacterNodePhase | null {
  if (value === "character_main" || value === "main") return "main";
  if (value === "character_turnaround" || value === "turnaround") return "turnaround";
  return null;
}

export function projectCharacterNodePresentation(
  node: Pick<CanvasNodeV2, "creative_role" | "prompt_preparation">,
): CharacterNodePresentation | null {
  const preparation = node.prompt_preparation;
  const phase = preparation?.character_phase ?? phaseFromRoleVariant(preparation?.role_variant ?? null);
  if (!phase) return null;
  return {
    occurrenceId: preparation?.occurrence_id ?? null,
    phase,
    phaseLabel: phase === "main" ? "Character Main" : "Character Turnaround",
  };
}
