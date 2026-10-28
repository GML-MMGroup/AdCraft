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
- Write for AI video generation, not a live shoot: every beat must be performable by a video model inside one continuous generated clip.
- Budget at most four clear actions per 15 seconds of runtime (scale proportionally for other durations). When the idea has more, cut the weakest escalation step instead of compressing several into one segment.
- Allowed in-clip techniques: push-in or crash zoom, pan, tilt, tracking, handheld feel, slow motion, a held still pose by the performers, and short on-screen captions. Do not rely on freeze frames, frame-exact cuts or sound hits, music that stops or changes on a cut, split screens, or anything that requires post-production editing.
- On-screen captions: at most two per 15 seconds, each 2 to 6 characters (or 1 to 3 short words), large, high-contrast, and placed in a fixed lower area; never long sentences.
- When a creative_method or reviewed brand_decisions is supplied, keep its mechanism: reveal timing, reversal position, when and how the product appears, and its structure (for example a logo held until the end, a late reveal, or a story-free form). Do not reshape it into a generic hook, product benefit, call-to-action sequence.
- When brand decisions describe editing-only techniques (freeze frames, beat-synced music cuts, frame-exact sound), keep their intent with an allowed in-clip technique instead.
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
