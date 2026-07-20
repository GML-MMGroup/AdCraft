---
skill_id: reference_asset_selection
name: Reference Asset Selection
description: Select product, character, scene, and storyboard references for video prompts.
---

# Purpose

Choose the right media assets for image and video model inputs.

# When To Use

Use for video generation and final composition planning.

# Inputs

Selected assets, character turnarounds, scene references, storyboard images, segment prompts.

# Output Guidance

List which asset roles should be passed to each downstream media model.

# Prompt Rules

- Prefer remote URL assets for remote model image inputs.
- Keep local paths for audit and preview.
- Preserve asset role and source node metadata.

# Do Not

- Do not pretend a local path is a public URL.
- Do not silently ignore required reference assets.
