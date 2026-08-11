---
skill_id: video_agent_bgm_direction
name: Video Agent BGM Direction
description: Shape instrumental music direction around the advertisement's mood and timing.
---

# Purpose

Create background-music guidance that supports the visual and emotional arc without replacing dialogue or sound design.

# Inputs

Use the creative objective, desired emotion, script beats, storyboard timing, requested duration, and explicit music constraints.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- Describe mood, tempo character, instrumentation, structure, transitions, and synchronization intent.
- Align intro, lift, and ending behavior to the advertisement's beat structure and duration.
- Leave appropriate space for narration, dialogue, and important source audio.
- Keep loop or fade intent clear when requested.

# Prompt Rules

- Keep music structure aligned with the supplied beat timing and emotional arc.

# Do Not

- Do not add voiceover, lyrics, or product sound effects unless the contract explicitly requests them.
- Do not ignore duration or introduce distracting structural changes.
- Do not choose provider credentials, model IDs, or transport parameters.
