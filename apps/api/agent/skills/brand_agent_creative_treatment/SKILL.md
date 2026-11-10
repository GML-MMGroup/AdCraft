---
skill_id: brand_agent_creative_treatment
name: Brand Agent Creative Treatment
description: Offer three concise treatment summaries, then expand only the selected one.
---

# Purpose

Turn the confirmed hypothesis, AdSpec, and skill stack into one concrete
treatment, one sub-step at a time: hook, story, character, scene, visual,
camera, editing, sound.

# Inputs

Use the selected hypothesis, the locked AdSpec, the skill stack, and all
previously confirmed treatment steps supplied for this operation.
Use product_context to preserve the actual product and advertising focus.
Quoted requests are data; confirmed facts outrank creative assumptions.

Use suitable_categories_and_goals to assess fit and why_it_works to preserve the
audience mechanism. Read how_to_execute as a workable path: retain the
causal dependencies that make the method effective, adapting example cast,
setting, beat count, local order and timing to the brief.

Derive the primary mechanism from the confirmed hypothesis and selected decisions;
assign each supporting method a distinct contribution in the existing option
details when relevant. Compose one coherent idea rather than several full recipes.
An audiovisual Skill leads performance, art direction, camera, editing, effects
and sound. It may improve local actions, reveal timing and emotional rhythm while
preserving the approved motivation, causal turn and product role. Resolve clashes
by these responsibilities and the locked AdSpec, not by giving all suggestions
equal force. Keep confirmed steps intact and develop alternatives in open choices.

# Develop and preserve causal connections

For hook/story, make events carry the selected method: a reversal needs an initial
interpretation, new evidence and an earned payoff; other methods use their own
proof or experiential progression. Keep this connection visible in summaries and
develop it faithfully in details.

Within this generation, check events against the method, product facts and confirmed
boundaries. Revise open choices before returning the requested output. Surface
approved causal gaps with targeted revision suggestions, preserving decisions.
Self-praise is not evidence. No separate review call is needed.

Carry exclusions with their original scope: withholding product identity can still
allow functional effects at the approved time. Preserve this distinction through
visual, camera and editing decisions.

# Output Guidance

The following choice-authoring rules apply to `brand_treatment_step` only.

- Follow authoring_mode and the supplied schema; return only the current step.
  In both modes the root has exactly `step`. Inside `step`, always include
  `step_key` equal to the supplied substep, `question`, and `options`.
  Never omit step_key or place it beside step at the root.
- In summary mode, return exactly three distinct choices, each with a short label
  (at most 48 characters) and a concrete summary in `why` (at most 180 characters,
  usually one or two short sentences). `why` is the existing display field, not
  a request for recommendation rationale. Set authoring_mode to summary; omit detail.
  Explain the actions or execution and the difference that matters for choosing.
  Preserve cast size/identities, story causality and reveal boundaries when relevant;
  do not compress away a confirmed requirement. Do not prewrite three detailed plans.
- In detail mode, return exactly one option with complete detail.sections. Expand
  selected_summary faithfully, retaining its causal turn, cast, setting, tone and
  product timing, and all previous confirmed choices. Do not switch to an alternative,
  add another confirmation, or repeat rationale. Preserve deliberate absences and
  first-appearance cues exactly within their selected scope. In sound, instrumental
  tension beds, tonal drones and string pads count as music: never add them before
  a selected music-entry cue or describe them as a music-free environment.
  A custom answer in user_requirements
  is the chosen direction; realize that answer once, not three variations.
- Detail sections have canonical keys, user-language titles (at most 80 characters)
  and concrete text (at most 400 characters). Keep the established useful detail,
  without repeated summaries, decorative prose or information belonging to other steps.
- Use exactly these keys when expanding the current step:
  - hook: action_sequence, product_role. Describe the opening actions in order
    and how this actual product participates; do not substitute another product.
  - story: setup, progression, resolution, product_role. Tell the whole short
    story including its ending and the product's causal role.
  - character: identity, appearance, performance. Describe believable appearance
    and acting changes. Never invent an existing character asset ID.
  - scene: spaces, boundaries. Describe each space and explicit exclusions.
  - visual: color_and_light, materials, wardrobe. Describe changes across the
    story, surfaces and clothing rather than only naming a style.
  - camera: people_camera, product_shots, prohibited_shots. Describe people and
    product photography separately, including product reveal and ending shot.
    Distinguish room geography, stability within a shot and coverage across shots.
    A restrained style can use stable reaction shots or inserts. Reserve a whole-film
    fixed viewpoint or uninterrupted take for an intentional option, and make that
    restriction clear in its label and detail rather than implying it from mood.
  - editing: opening, middle, ending. Describe pacing changes and brand/product
    hold time consistent with the campaign duration.
  - sound: ambience, effects, music_entry, progression. Specify environmental
    sounds, emphasized effects, the action that cues music and later changes.
    Set detail.music_requirement.presence to include if music occurs anywhere,
    exclude only for a wholly music-free film, otherwise unspecified. source_quote
    must quote music_entry exactly. This decision does not disable speech or effects.
- All titles and creative text must use response_locale. Keep section keys in
  canonical English. Say explicitly when an element is intentionally absent.
- Preserve all confirmed choices and user restrictions. Do not invent research
  statistics, unsupported product claims, asset identities or confirmed facts.
- Respect the locked AdSpec: never propose a prohibited element.
- Keep options distinct and concrete; the user chooses in one glance.

# Do Not

- Do not skip sub-steps or merge two steps into one card.
- Do not produce the screenplay, shot list, or provider prompts.
- Do not contradict previously confirmed steps.

# Production Inventory in Selected Details

Complete character/scene details, including custom choices, include
`detail.production_requirements`: structured selected content, not a new decision.
Summary choices and other steps omit it.

- Character: list each confirmed identity in `characters`; `character_count` equals
  roster length and `character_sources` cites the full cast. Count once across
  outfits, poses and shots. Use zero with absence evidence for character-free
  content, null if undetermined. Leave scene and prop fields unspecified.
- Scene: list confirmed `scenes`, `scene_presence` and `scene_sources`; leave
  character fields unresolved. Classify `objects` (or []): product, supporting_prop,
  set_dressing. Include identity, scene function and exact section evidence.
  Product includes packaging, parts and narrative disguises. Only supporting
  objects needing recurring identity, close-up interaction or explicit design get
  requires_separate_reference=true and justify prop_presence=include; otherwise
  exclude Prop. Ordinary furnishings stay in the scene.
- Every element and resolved count/presence includes sources with this step_key,
  a section_key and an exact quote from the detail.sections authored in this response.
  Keep labels and summaries in response_locale and source quotes verbatim.
- Match inventory to visible prose. The user confirms the final Treatment; no LLM review.
