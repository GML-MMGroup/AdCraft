---
skill_id: visual_continuity_check
name: Visual Continuity Check
description: Check role, scene, product, and timing continuity across shots.
---

# Purpose

Keep storyboard prompts consistent before media generation.

# When To Use

Use for storyboard and video prompt planning.

# Inputs

Storyboard scenes, product references, character design, scene design, generated reference assets.

# Output Guidance

List continuity constraints that downstream image and video nodes should preserve.

# Prompt Rules

- Check product consistency.
- Check character identity consistency.
- Check scene and lighting consistency.
- Check shot duration totals.

# Do Not

- Do not act as a separate frontend QA node.
- Do not rewrite approved story beats unless needed for consistency.
