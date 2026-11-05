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

Selected creative_methods provide story_structure, hook_methods, product_role,
common_mistakes, unsuitable_cases, consumer_psychology, cross_category_examples,
suitable_categories_and_goals, why_it_works, and how_to_execute when available.
Use suitable_categories_and_goals to assess fit and why_it_works to preserve the
reason the mechanism engages the audience.
Use consumer_psychology to preserve the audience mechanism and cross_category_examples
to understand how it transfers. Read how_to_execute as a workable path: retain
the causal dependencies that make the method effective, while adapting example
cast, setting, beat count, local order and timing to the brief.

Derive the primary mechanism from the confirmed hypothesis and selected decisions;
assign each supporting method a distinct contribution in the existing option
details when relevant. Compose one coherent idea rather than several full recipes.
An audiovisual Skill leads performance, art direction, camera, editing, effects
and sound. It may improve local actions, reveal timing and emotional rhythm while
preserving the approved motivation, causal turn and product role. Resolve clashes
by these responsibilities and the locked AdSpec, not by giving all suggestions
equal force. Keep confirmed steps intact and develop alternatives in open choices.

# Output Guidance

The following choice-authoring rules apply to `brand_treatment_step` only.

- Follow authoring_mode and the supplied schema; return only the current step.
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
  add another confirmation, or repeat rationale. A custom answer in user_requirements
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

# Bounded Review Operation

For `brand_treatment_review`, return only `production_requirements` and advisory
`findings` for the supplied `treatment_document`; do not return another step or
three alternatives. Keep every confirmed section unchanged.

- Normalize distinct character identities, not appearances, outfits or storyboard
  cells. Return character_count and exactly that many character summaries only
  when the selected content establishes a complete cast. Otherwise use null.
  Zero requires explicit absence evidence; missing information is not absence.
- Describe the confirmed spaces separately. Resolve scene_presence and
  prop_presence only from explicit selected content; otherwise use unspecified.
  The advertised product is not an extra prop by default.
- Every inventory element and resolved presence/count needs sources containing
  exact step_key, section_key and quote copied from the supplied section text.
- Check whether camera restrictions match the described coverage and whether exact
  speech, pauses and required actions fit the duration at the intended delivery.
  Surface conflicts as source-referenced findings; do not rewrite selected choices.
- Check story/character/scene continuity, color and light, pacing against Campaign
  duration, Brand/AdSpec alignment and the stated sound execution limitations.
  Return at most eight concise info/warning findings with exact source references.
  An empty findings list means this bounded review found no specific issue; it is
  not a guarantee of creative quality or execution support.
- Findings are advisory. Do not rewrite, resolve, silently harmonize or override
  confirmed decisions. Do not invent identity counts, asset IDs or authorization,
  provider capabilities, extra mixing support, or unsupported product claims.
- Render labels, summaries and finding messages in response_locale. Keep field
  names, source keys and enums in canonical English; quotes remain verbatim.
