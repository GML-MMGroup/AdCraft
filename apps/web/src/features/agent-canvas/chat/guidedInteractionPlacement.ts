import type { GuidedInteractionV1 } from "../../../types-v2.ts";

export function guidedInteractionContentVersion(
  interaction: GuidedInteractionV1 | null,
): string {
  return interaction
    ? `${interaction.interaction_id}:${interaction.revision}:${interaction.status}`
    : "";
}

export function shouldRenderStandaloneInteraction(
  interaction: GuidedInteractionV1 | null,
): boolean {
  return interaction?.status === "open";
}
