import type { GuidedInteractionV1 } from "../../../types-v2.ts";

/** Brand hypothesis and Treatment cards may grow beyond the initial three options. */
export function isBrandCustomInputCapabilityId(capabilityId: string): boolean {
  return capabilityId.startsWith("brand_hypothesis") || capabilityId.startsWith("brand_treatment");
}

export function isBrandCustomInputCard(interaction: GuidedInteractionV1): boolean {
  return interaction.content.content_kind === "concept_choice"
    && isBrandCustomInputCapabilityId(interaction.content.capability_id);
}
