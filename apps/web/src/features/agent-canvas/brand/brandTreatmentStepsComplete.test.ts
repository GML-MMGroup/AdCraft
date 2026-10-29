import { expect, it } from "vitest";
import type { BrandTreatmentStepResultV1 } from "./brandDecisions";
import { brandTreatmentStepsComplete } from "./brandTreatmentStepsComplete";

const steps: BrandTreatmentStepResultV1[] = (
  ["hook", "story", "character", "scene", "visual", "camera", "editing", "sound"] as const
).map(step_key => ({ step_key, selected_label: step_key, detail: "Confirmed detail", confirmed_at: "2026-10-28T00:00:00Z" }));

it("requires a panel with confirmed treatment steps", () => {
  expect(brandTreatmentStepsComplete(null)).toBe(false);
  expect(brandTreatmentStepsComplete(undefined)).toBe(false);
  expect(brandTreatmentStepsComplete({ treatment_steps: [] })).toBe(false);
});

it("accepts all eight distinct steps in any order", () => {
  expect(brandTreatmentStepsComplete({ treatment_steps: steps })).toBe(true);
  expect(brandTreatmentStepsComplete({ treatment_steps: [...steps].reverse() })).toBe(true);
});

it.each(steps)("requires the $step_key step even when eight entries are present", missing => {
  const incomplete = steps.filter(step => step.step_key !== missing.step_key);
  expect(brandTreatmentStepsComplete({ treatment_steps: incomplete })).toBe(false);
  expect(brandTreatmentStepsComplete({ treatment_steps: [...incomplete, incomplete[0]] })).toBe(false);
});
