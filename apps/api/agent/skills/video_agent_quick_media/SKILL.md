---
skill_id: video_agent_quick_media
name: Video Agent Quick Media
description: Turn a bounded free-generation objective into one clear media prompt plan.
---

# Purpose

Create a concise, filmable or audible media direction for the requested image, video, or audio operation.

# Inputs

Use only the current user objective, media kind, approved references, and deterministic constraints supplied for this operation.

# Output Guidance

- Keep the idea concrete, visually or audibly clear, and directly tied to the objective.
- Preserve identity and brand constraints from approved references.
- Include only details relevant to the requested media kind.
- State uncertainty rather than inventing missing product or identity facts.

# Prompt Rules

- Produce one bounded prompt plan for the exact media operation requested by Python.

# Do Not

- Do not select another capability, operation, provider, model, duration, aspect ratio, or resolution.
- Do not include sibling prompts, private Drafts, credentials, local paths, or media bytes.
- Do not submit media generation or claim that an asset already exists.
