import type { BrandBriefSummary, BrandTreatmentDocument, TreatmentDetail, TreatmentSection } from "./brandDecisions";
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Treatment document object");
  return value as Record<string, unknown>;
};
function sections(value: unknown): TreatmentSection[] {
  if (!Array.isArray(value)) throw new Error("Invalid Treatment sections");
  return value.map(item => {
    const section = object(item);
    if (![section.key, section.title, section.text].every(v => typeof v === "string")) throw new Error("Invalid Treatment section text");
    return { key: section.key as string, title: section.title as string, text: section.text as string };
  });
}
export function readTreatmentDetail(value: unknown): TreatmentDetail | null {
  return value == null ? null : { sections: sections(object(value).sections) };
}
export function readBrandBrief(value: unknown): BrandBriefSummary | null {
  if (value == null) return null;
  const brief = object(value);
  for (const key of ["values", "inherited_values", "unresolved_fields"]) {
    if (!Array.isArray(brief[key])) throw new Error("Invalid brand brief");
  }
  return brief as unknown as BrandBriefSummary;
}
export function readTreatmentDocument(value: unknown): BrandTreatmentDocument | null {
  if (value == null) return null;
  const doc = object(value);
  if (typeof doc.complete !== "boolean" || typeof doc.content_digest !== "string") throw new Error("Invalid Treatment completeness");
  for (const key of ["missing_sections", "execution_limitations", "authorized_asset_references", "treatment_steps"]) {
    if (!Array.isArray(doc[key])) throw new Error("Invalid Treatment document collection");
  }
  const steps = (doc.treatment_steps as unknown[]).map(value => {
    const step = object(value);
    if (typeof step.step_key !== "string" || typeof step.selected_label !== "string") throw new Error("Invalid Treatment step");
    return { ...step, structured_detail: readTreatmentDetail(step.structured_detail) };
  });
  return { ...doc, brand_profile: readBrandBrief(doc.brand_profile), campaign_brief: readBrandBrief(doc.campaign_brief),
    product_presentation: sections(doc.product_presentation), treatment_steps: steps } as unknown as BrandTreatmentDocument;
}
