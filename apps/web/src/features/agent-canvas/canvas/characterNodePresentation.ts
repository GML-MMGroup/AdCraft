import type { CanvasNodeV2 } from "../../../types-v2.ts";

export type CharacterNodePhase = "main" | "turnaround";

export interface CharacterNodePresentation {
  occurrenceId: string | null;
  phase: CharacterNodePhase | null;
  phaseLabel: "Character" | "Character Main" | "Character Turnaround";
}

function phaseFromRoleVariant(value: unknown): CharacterNodePhase | null {
  if (value === "character_main" || value === "main" || value === "identity_master") return "main";
  if (value === "character_turnaround" || value === "turnaround") return "turnaround";
  return null;
}

export function projectCharacterNodePresentation(
  node: Pick<CanvasNodeV2, "creative_role" | "prompt_preparation" | "metadata" | "structured_content">,
): CharacterNodePresentation | null {
  if (node.creative_role !== "character") return null;
  const preparation = node.prompt_preparation;
  const phase = phaseFromRoleVariant(node.metadata.character_phase)
    ?? phaseFromRoleVariant(node.structured_content.character_asset_kind)
    ?? preparation?.character_phase
    ?? phaseFromRoleVariant(preparation?.role_variant);
  const occurrenceId = [node.metadata.occurrence_id, node.structured_content.occurrence_id, preparation?.occurrence_id]
    .find((value): value is string => typeof value === "string" && value.length > 0) ?? null;
  return {
    occurrenceId,
    phase,
    phaseLabel: phase === "main" ? "Character Main" : phase === "turnaround" ? "Character Turnaround" : "Character",
  };
}
