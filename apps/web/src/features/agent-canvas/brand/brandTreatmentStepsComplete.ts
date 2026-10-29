import type { BrandDecisionPanelV1 } from "./brandDecisions";

const treatmentStepKeys = [
  "hook", "story", "character", "scene", "visual", "camera", "editing", "sound",
] as const;

export function brandTreatmentStepsComplete(
  panel: Pick<BrandDecisionPanelV1, "treatment_steps"> | null | undefined,
): boolean {
  return Boolean(panel && treatmentStepKeys.every((key) => (
    panel.treatment_steps.some((step) => step.step_key === key)
  )));
}
