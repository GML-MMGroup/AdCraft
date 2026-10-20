---
skill_id: video_agent_scene_design
name: Video Agent Scene Design
description: Define reusable environments with stable spatial, lighting, and atmosphere rules.
---

# Purpose

Create pure scene directions for one primary location that support the script and remain spatially consistent across views.

# Inputs

Use the World Setting, script needs, product use case, explicit scene constraints, and approved scene references.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- Name one primary location for Scene Main. If the concept spans several places, choose the primary place and keep the others out of Main.
- Specify the primary location's architecture, spatial layout, light, color, atmosphere, and important anchors.
- Keep the environment reusable and open enough for later product and character placement.
- Preserve spatial structure, palette, and lighting across requested Multi-view viewpoints of that same location.
- Separate environment design from characters, actions, and unrelated products.

# Prompt Rules

- Keep spatial anchors and visual continuity explicit so every Multi-view viewpoint remains in the same place.

# Do Not

- Do not add people or unrelated products to pure scene references.
- Do not combine conflicting layouts or unrelated environments.
- Do not include provider payloads, local paths, or sibling capability prompts.
