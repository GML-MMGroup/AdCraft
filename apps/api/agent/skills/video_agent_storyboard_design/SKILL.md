---
skill_id: video_agent_storyboard_design
name: Video Agent Storyboard Design
description: Convert approved script beats into ordered, visually continuous storyboard directions.
---

# Purpose

Organize the approved script into bounded Storyboard Sequences and executable image directions while preserving product, character, and scene continuity.

# Inputs

Use the approved script, product identity, character and scene designs, timing, and approved references for the owning shot.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- One Storyboard Sequence equals one ordered 3x3 storyboard grid and one downstream video segment.
- Shots, camera changes, panels, and story beats are internal content of a Sequence; organize them into its nine-panel progression instead of promoting each one to a separate Sequence.
- Preserve platform-supplied Sequence counts and timing windows exactly. When they are not supplied, use the minimum number of contiguous Sequences required by the total duration and the 15-second maximum.
- Define ordered shot purpose, action, framing, text, timing, and relevant input roles.
- Keep each beat concrete enough to occupy a clear place within its owning storyboard grid and video segment.
- Preserve product packaging and proportions, character identity, and scene layout, lighting, and palette.
- Keep total shot timing compatible with the requested advertisement duration.
- Give each adjacent segment a distinct narrative responsibility with non-overlapping primary beats.
- Express each segment's opening state and closing state through the existing sequence summary, narrative goal, and panel fields.
- When prior-segment context is supplied, begin with a bounded continuity handoff from its closing state, then advance to a different primary action and next state.

# Prompt Rules

- Bind every shot direction to its owning beat and approved reference roles.
- Carry only the prior closing state needed to establish the next opening state.

# Do Not

- Never convert the script shot count into the Sequence count.
- Do not mix identities or borrow private Drafts and references from another shot.
- Do not create abstract, unfilmable beats or silently omit required product visibility.
- Do not duplicate an earlier segment's complete beat progression as a generic continuation.
- Do not submit media tasks or include provider credentials and local paths.
