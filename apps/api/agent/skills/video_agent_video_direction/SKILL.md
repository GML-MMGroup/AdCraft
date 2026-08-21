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
- Preserve product, character, scene, lighting, and timing continuity across adjacent shots.
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
