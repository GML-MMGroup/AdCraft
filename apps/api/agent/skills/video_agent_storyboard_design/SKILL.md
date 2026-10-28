---
skill_id: video_agent_storyboard_design
name: Video Agent Storyboard Design
description: Convert approved script beats into ordered, visually continuous storyboard directions.
---

# Purpose

Keep confirmed audible speech in the narrative and sequence timing, including speaker and exact words; image panels depict the accompanying action without rendering that speech as captions. Do not convert required dialogue into on-screen copy. Separate BGM generation does not remove native Video sound.

Organize the approved script into bounded Storyboard Sequences and executable image directions while preserving product, character, and scene continuity.

# Inputs

Use the approved script, product identity, character and scene designs, timing, and approved references for the owning shot.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- One Storyboard Sequence equals one ordered 3x3 storyboard grid and one downstream video segment.
- Shots, camera changes, panels, and story beats are internal content of a Sequence; organize them into its nine-panel progression instead of promoting each one to a separate Sequence.
- Each Sequence carries at most four primary actions; the nine panels show the progression of those actions (setup, action, reaction), not nine different events.
- Allowed in-clip techniques: push-in or crash zoom, pan, tilt, tracking, handheld feel, slow motion, a held still pose by the performers, and short on-screen captions. Do not rely on freeze frames, frame-exact cuts or sound hits, music that stops or changes on a cut, split screens, or anything that requires post-production editing.
- On-screen captions: at most two per 15 seconds, each 2 to 6 characters (or 1 to 3 short words), large, high-contrast, and placed in a fixed lower area; never long sentences.
- When brand decisions describe editing-only techniques (freeze frames, beat-synced music cuts, frame-exact sound), keep their intent with an allowed in-clip technique instead.
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
