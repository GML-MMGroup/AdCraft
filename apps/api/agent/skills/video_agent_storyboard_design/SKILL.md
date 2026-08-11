---
skill_id: video_agent_storyboard_design
name: Video Agent Storyboard Design
description: Convert approved script beats into ordered, visually continuous storyboard directions.
---

# Purpose

Break the script into executable shots and image directions while preserving product, character, and scene continuity.

# Inputs

Use the approved script, product identity, character and scene designs, timing, and approved references for the owning shot.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- Define ordered shot purpose, action, framing, text, timing, and relevant input roles.
- Keep each beat concrete enough for one storyboard image and a short video segment.
- Preserve product packaging and proportions, character identity, and scene layout, lighting, and palette.
- Keep total shot timing compatible with the requested advertisement duration.
- Give each adjacent segment a distinct narrative responsibility with non-overlapping primary beats.
- Express each segment's opening state and closing state through the existing sequence summary, narrative goal, and panel fields.
- When prior-segment context is supplied, begin with a bounded continuity handoff from its closing state, then advance to a different primary action and next state.

# Prompt Rules

- Bind every shot direction to its owning beat and approved reference roles.
- Carry only the prior closing state needed to establish the next opening state.

# Do Not

- Do not mix identities or borrow private Drafts and references from another shot.
- Do not create abstract, unfilmable beats or silently omit required product visibility.
- Do not duplicate an earlier segment's complete beat progression as a generic continuation.
- Do not submit media tasks or include provider credentials and local paths.
