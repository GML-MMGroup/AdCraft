export const intakeRepairPolicy = [
  "Repair only the reported violations and preserve the original intake policy, route, supported facts, and response locale.",
  "Only context.user_input supplies source_quote evidence; recent_messages and workflow state are context, not new user assertions.",
  "When the current message does not support a reported fact, omit the unsupported element, control, or directive rather than reusing a historical quote.",
  "Do not substitute an unrelated current-message substring just to satisfy quote validation.",
  "Omitting an unsupported patch field leaves persisted requirements unchanged; it does not exclude an element or clear earlier requirements.",
  "For this repair, return exactly one JSON object matching the supplied schema in assistant content. Do not call tools.",
].join(" ");
