---
skill_id: video_agent_script_authoring
name: Video Agent Script Authoring
description: Shape a filmable short-ad idea into paced, audience-facing script beats.
---

# Purpose

Write a playable advertising script that connects product value to audience motivation.

# Inputs

Use the creative objective, product truth, audience, campaign appeal, duration constraint, World Setting, and approved references.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- Keep the core idea concrete, visual, and achievable in the requested duration.
- When a creative_method or reviewed brand_decisions is supplied, keep its mechanism: reveal timing, reversal position, when and how the product appears, and its structure (for example a logo held until the end, a late reveal, or a story-free form). Do not reshape it into a generic hook, product benefit, call-to-action sequence.
- Only when no creative method or brand decision applies, begin with a clear hook, demonstrate the product benefit, and end with a concise call to action.
- Keep spoken and on-screen lines natural, short, and suitable for viewers.
- Keep timing and beat order internally consistent while preserving explicit user copy.
- Preserve confirmed dialogue and voiceover as audible lines with speakers, delivery, and timing. Do not rewrite a spoken line as a subtitle or infer silence from `audio_mode=bgm_only`; that control limits separate audio generation to BGM, not native Video sound. Respect explicit no-dialogue or silent creative decisions.

# Prompt Rules

- Keep audience-facing language separate from internal planning and production guidance.

# Do Not

- Do not place raw briefs, workflow labels, or production notes in audience-facing dialogue.
- Do not invent product claims or let the product become an incidental background prop.
- Do not author storyboard camera instructions or provider payloads.
