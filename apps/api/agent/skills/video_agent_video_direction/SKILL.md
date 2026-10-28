---
skill_id: video_agent_video_direction
name: Video Agent Video Direction
description: Turn storyboard beats into ordered motion directions with stable visual continuity.
---

# Purpose

Plan coherent video segments from approved storyboard shots without submitting provider work.

# Inputs

Use the owning shot, its selected storyboard references, product and identity constraints, requested timing, and provider limits supplied by Python.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- Preserve storyboard order and define clear subject action, camera motion, framing, and transition intent.
- Keep camera motion limited and legible within each segment.
- Describe at most four primary actions for the segment, in order, each with its own clear time window of at least 2.5 seconds.
- Express camera emphasis as in-clip camera motion (for example 'the camera quickly pushes in to a close-up of his face'); never write freeze frames, frame-exact timing, beat-synced music changes, or editing instructions.
- On-screen captions: at most two per 15 seconds, each 2 to 6 characters (or 1 to 3 short words), large, high-contrast, and placed in a fixed lower area; never long sentences.
- When brand decisions describe editing-only techniques (freeze frames, beat-synced music cuts, frame-exact sound), keep their intent with an allowed in-clip technique instead.
- Preserve product, character, scene, lighting, and timing continuity across adjacent shots.
- Preserve confirmed dialogue and voiceover with speaker, exact words, language, delivery, and local timing; retain ambience and synchronized action effects. Exclude background music only. `audio_mode=bgm_only` does not require silent Video, and a no-text image policy does not remove audible speech. Respect explicit silence or no-dialogue decisions.
- Reference only the approved assets supplied for the same shot.
- Define one segment-specific motion progression from its opening state through a distinct primary action to its closing state.
- Use bounded prior-segment context only for the continuity handoff into the owning segment.
- Treat the target output style as authoritative; a non-style reference supplies identity, spatial, or action facts without transferring its rendering medium.

# Prompt Rules

- Keep motion and camera instructions bounded to the owning shot and supplied constraints.
- Preserve the supplied reference facts while following the target Video rendering medium.

# Do Not

- Do not invent fixed duration, aspect-ratio, resolution, model, or provider settings.
- Do not submit tasks, fabricate completed URLs, or convert local paths into remote references.
- Do not import sibling full prompts, private Drafts, credentials, or media bytes.
