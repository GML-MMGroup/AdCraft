export const brandFormSupplementalRepairPolicy = [
  "Repair the BrandStrategyOutputV1 result only for the reported supplemental form violations.",
  "For each requested slot, keep at most the supplied three generated options and replace repeated or near-duplicate labels with concrete alternatives that are genuinely new relative to previous_options_by_slot.",
  "Return at least two genuinely new options per requested slot. Previous options may remain for comparison, but do not return only previous options and do not rewrite them lightly.",
  "Do not change stage, requested slots, response locale, contract shape, or any confirmed value.",
].join(" ");
