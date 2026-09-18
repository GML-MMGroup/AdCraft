---
skill_id: brand_agent_brand_strategy
name: Brand Agent Brand Strategy
description: Collect brand memory and campaign brief slots through short questions with exactly three options.
---

# Purpose

Gather the Brand Memory and Campaign slot tables by asking one bounded question
at a time. Each question offers exactly three short options; the user may also
answer freely or delegate the value to you.

# Inputs

Use the confirmed conversation context, the current slot values with their
provenance, and the active stage ("brand-memory" or "campaign") supplied for
this operation.

# Output Guidance

- Return structured slot updates with provenance: user_confirmed only when the
  user explicitly stated or confirmed the value.
- Return exactly one question card with exactly three options.
- Option labels are at most 24 characters; the optional `why` is at most 120
  characters.
- Ask only about the next unfilled required slot; skip already confirmed slots.
- When the user delegated a value, mark it agent_recommended and continue to
  the next slot.

# Do Not

- Do not invent slot ids outside the provided schema.
- Do not ask multiple slot questions in one card.
- Do not write long option labels or explanations.
- Do not produce screenplay, shots, or media instructions.
