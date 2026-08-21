---
skill_id: video_agent_character_design
name: Video Agent Character Design
description: Define brand-fit characters and stable identity guidance for consistent views.
---

# Purpose

Create a small cast whose role, appearance, temperament, and identity support the advertising concept.

# Inputs

Use the audience, campaign tone, script context, explicit character constraints, and approved character references.

# Output Guidance

- Render user-visible and audible content in `response_locale`; keep internal controls in English.

- Return one lean identity-master design result for Character materialization.
- Python derives the Turnaround companion from the validated identity master.
- Make character descriptions stable enough for consistent image and video generation.
- Define role, age range, face, hair, outfit, body type, silhouette, temperament, and brand fit when relevant.
- Separate character identity from action and environment.
- Keep the Character Main composition to one full-body illustrated person on a seamless light-neutral background with no environmental objects.
- For Turnaround guidance, preserve one identity across exactly three unlabeled full-body views: forward-facing, exact side profile, and rear-facing.

# Prompt Rules

- Repeat stable identity details consistently across every requested character view.
- Keep Turnaround sheets free of headings, orientation labels, captions, typography, logos, and watermarks.

# Do Not

- Do not construct a two-Node payload or assign canvas Node or Binding IDs.
- Do not write a provider prompt or choose provider request parameters.
- Do not add unnecessary people or change identity between views.
- Do not embed complex scenes in pure character references.
- Do not choose provider parameters or expose private reference locations.
