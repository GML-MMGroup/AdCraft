---
skill_id: brand_agent_full_script
name: Brand Agent Complete Screenplay
description: Write one complete timed advertising screenplay after the user chooses direct script production.
---

# Task

Write one complete advertising screenplay in response_locale from the confirmed
Brand brief, selected hypothesis, AdSpec, product references, creative methods
and audiovisual style. The user has delegated the remaining creative decisions
and requested production immediately after this script. Return one finished
script, with its ending, rather than choices or another questionnaire.

# Screenplay

Return a short title and a readable Markdown screenplay. Start with estimated
duration, cast, locations and tone. Organize it into named acts with time ranges.
For each act, describe visible action and camera coverage, attribute every spoken
line to its speaker, and mark performance, ambience, effects, music and captions
where useful. Finish with the product reveal, brand message and ending hold
appropriate to the selected concept. Use only confirmed brand/product facts;
leave an unknown brand name as an explicit placeholder rather than inventing one.

Preserve the selected story mechanism and style. A suspense reversal needs an
initial interpretation, escalating evidence and an earned reveal; another
mechanism uses its own progression. The format does not require every advertisement
to feature a clinic, patient, nurse or reversal. Cast, settings and actions belong
to this brief. Respect reveal boundaries and product reference geometry, grip,
orientation and actual function when people handle it.

Fit dialogue and physical action into the confirmed total duration. Budget the
spoken lines at a natural pace before assigning act ranges, include reactions
and product/brand hold time, and shorten dialogue when necessary. Time ranges
must cover the film in order. Write speakable lines with clear intent and a
consistent causal chain; check that the opening and ending do not contradict.
The screenplay is human-readable creative authority, not provider prompts.

# Production metadata

In the same result, copy the screenplay's full cast and locations into
production_requirements. Count distinct identities once across shots. Resolve
character_count and scene_presence, including explicit absence for a film with
no characters or locations. Summaries describe each identity or space for later
prompt authoring. Treat the advertised product separately from optional props.

Classify physical objects in production_requirements.objects. For each, name its
identity and scene function, quote its screenplay evidence, and assign ownership:
product, supporting_prop, or set_dressing. The advertised item stays product even
when handled by a character, disguised in the story, or revealed at the ending;
its packaging and functional components do not become a second Prop design.
requires_separate_reference is true only for a supporting object whose recurring
appearance, close-up interaction or explicit user requirement warrants its own
reference. Ordinary furnishings belong to the scene. Resolve prop_presence from
those independently designed supporting objects; a product reveal alone is not
evidence for including Props. Use [] when there are no physical objects.

All inventory sources use step_key="story", section_key="screenplay", with exact
quotes from the screenplay field. Make cast and location declarations explicit
so they can support counts and presence. Set music_requirement independently
of dialogue and effects, quoting the screenplay's music direction exactly.

Return exactly BrandScreenplayV1. Completion means the visible script contains
the full story, timed actions, all dialogue, sound cues and ending, and its typed
cast, locations and music agree with that text. Python persists and displays the
script and advances the journey; this operation performs no workflow actions.
