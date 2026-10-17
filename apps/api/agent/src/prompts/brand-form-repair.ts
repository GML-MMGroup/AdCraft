export const brandFormSupplementalRepairPolicy = [
  "Repair the BrandStrategyOutputV1 result only for the reported supplemental form violations.",
  "For each requested slot, keep at most the supplied three generated options and replace repeated or near-duplicate labels with concrete alternatives that are genuinely new relative to previous_options_by_slot.",
  "Return at least two genuinely new options per requested slot. Previous options may remain for comparison, but do not return only previous options and do not rewrite them lightly.",
  "Do not change stage, requested slots, response locale, contract shape, or any confirmed value.",
].join(" ");

export const brandFormRepairPolicy = [
  "Repair the BrandStrategyOutputV1 result only for the reported Brand foundation form violations.",
  "Return exactly one form card for every expected_slot_ids entry, using each slot id exactly once.",
  "Preserve the stage, response locale, confirmed values, and contract shape; do not omit rows or invent slots.",
  "Each card must contain three concrete recommendations and must not use the custom option; Python adds the custom option after validation.",
].join(" ");

export const brandTreatmentReviewRepairPolicy = [
  "Repair the BrandTreatmentReviewOutputV1 result only for the reported source-quote violations.",
  "For every invalid reference, preserve step_key and section_key and replace only quote with an exact contiguous substring of the supplied allowed section text.",
  "Copy the allowed section text exactly, including its original words and punctuation; do not paraphrase, summarize, or invent section text.",
  "Preserve all valid findings, production decisions, and the contract shape.",
].join(" ");
