"""Deterministic compiler for typed Agent Canvas role briefs."""

from __future__ import annotations

from hashlib import sha256
import json
import re

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_prompt_assertion import PromptAssertionEvidenceV1
from app.schemas.agent_canvas_ad_media import (
    BgmContentV2,
    CharacterDesignAssetContentV2,
    DesignAssetContentV2,
    SceneBoardPanelV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VideoSegmentContentV2,
    VisualStyleContractV2,
)
from app.schemas.agent_canvas_role_prompt_preparation import (
    BgmRoleBriefV2,
    CharacterMainRoleBriefV2,
    CharacterTurnaroundRoleBriefV2,
    CompiledNodePromptV2,
    FreeMediaRoleBriefV2,
    ProductMainRoleBriefV2,
    ProductMultiviewRoleBriefV2,
    PropRoleBriefV2,
    RolePromptCompactionDecisionV2,
    ResolvedNodeParameterV2,
    RoleCreativeBriefV2,
    RoleCreativeBriefMemberV2,
    RolePromptPreparationContextV2,
    SceneBoardRoleBriefV2,
    ScriptRoleBriefV2,
    StoryboardGridRoleBriefV2,
    VideoSegmentRoleBriefV2,
    WorldViewRoleBriefV2,
)
from app.services.agent_canvas_prompt_assertion_policy import (
    PRODUCT_MULTIVIEW_VIEWS,
    PromptAssertionPolicyRegistry,
    source_snapshots_from_context,
)
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistry
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)
from app.services.agent_canvas_reference_style_authority import (
    ReferenceAwareAssetPromptRenderer,
    ReferenceStyleAuthorityPolicyResolver,
)
from app.services.agent_canvas_reference_conditioning import ReferenceConditioningPlanResolver
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV2,
    WorldSettingCoreV2,
    WorldSettingDocumentV2,
)


_ROLE_PROMPT_CONFLICTS: dict[str, tuple[str, ...]] = {
    "product_main": (
        "person",
        "people",
        "using the product",
        "application scene",
        "narrative environment",
        "active scene",
        "lifestyle scene",
        "lifestyle image",
    ),
    "prop": (
        "person",
        "people",
        "product interaction",
        "using the product",
        "active scene",
    ),
    "character_main": (
        "photorealistic",
        "photo-realistic",
        "photograph",
    ),
    "character_turnaround": (
        "label",
        "labels",
        "caption",
        "captions",
        "panel text",
        "annotation",
    ),
    "scene_board": (
        "character",
        "characters",
        "product",
        "products",
        "prop",
        "props",
        "narrative action",
        "plot progression",
        "active character",
    ),
}


class AgentCanvasRolePromptCompiler:
    """Compile stable provider-neutral prompts from one strict role brief."""

    def __init__(self, registry: RolePromptRecipeRegistry | None = None) -> None:
        self._registry = registry or RolePromptRecipeRegistry()
        self._reference_policy = AgentCanvasRoleReferencePolicyService()
        self._assertion_policies = PromptAssertionPolicyRegistry()

    def compile(
        self,
        brief: RoleCreativeBriefV2 | RoleCreativeBriefMemberV2,
        context: RolePromptPreparationContextV2,
        *,
        parameters: tuple[ResolvedNodeParameterV2, ...] = (),
    ) -> CompiledNodePromptV2:
        concrete_brief = brief.root if isinstance(brief, RoleCreativeBriefV2) else brief
        if concrete_brief.role_variant != context.role_variant:
            raise _error("node_prompt_brief_invalid", "Role brief variant does not match context.")
        recipe = self._registry.resolve(context.role_variant)
        policy = self._assertion_policies.resolve_for_video_audio(
            recipe.recipe_id,
            recipe.recipe_version,
            native_audio_required=(
                context.role_variant == "video_segment"
                and any(item.name == "generate_audio" and item.value is True for item in parameters)
            ),
        )
        role_policy = self._reference_policy.for_prompt_variant(context.role_variant)
        if isinstance(concrete_brief, ProductMultiviewRoleBriefV2):
            concrete_brief = concrete_brief.model_copy(update={"views": PRODUCT_MULTIVIEW_VIEWS})
        brief_payload = concrete_brief.model_dump(mode="json")
        brief_digest = _digest(brief_payload)
        compaction_decisions = _compaction_decisions(
            context,
            recipe,
            brief_digest=brief_digest,
        )
        prompt, negative = _render(concrete_brief)
        _validate_role_prompt_text(context.role_variant, prompt)
        style_authority = ReferenceStyleAuthorityPolicyResolver().resolve(context)
        conditioning_plan = ReferenceConditioningPlanResolver().resolve(context)
        if style_authority is not None:
            prompt = ReferenceAwareAssetPromptRenderer().render(
                prompt,
                context.style_projection,
                style_authority,
                explicit_controls=context.explicit_controls,
                conditioning_plan=conditioning_plan,
            )
        elif context.style_projection:
            _validate_role_prompt_text(context.role_variant, context.style_projection)
            prompt = f"{prompt} Visual style: {context.style_projection.strip()}"
        self._validate_required_references(recipe.reference_purposes, context)
        self._reference_policy.require_derivative_prompt_bindings(
            context.role_variant,
            context.bindings,
        )
        if context.role_variant == "character_turnaround":
            parent = context.bindings[0]
            if parent.occurrence_id != context.occurrence_id or parent.character_phase != "main":
                raise _error(
                    "character_parent_provenance_invalid",
                    "Character Turnaround requires the exact same-occurrence Main provenance.",
                )
        world_view_compacted = any(
            item.outcome == "compacted" and item.block_id == context.world_view_block_id
            for item in compaction_decisions
        )
        if (
            context.world_view_projection
            and "world_view" in recipe.allowed_context_selectors
            and not world_view_compacted
        ):
            prompt = f"{prompt} Applicable world rules: {context.world_view_projection.strip()}"
        prompt = f"{prompt}\n\n{policy.assertion_block}"
        if (
            context.role_variant in {"video_segment", "free_video"}
            and context.video_representation_mode == "illustration_to_live_action"
        ):
            prompt = f"{prompt}\n\n{_LIVE_ACTION_IDENTITY_GUARDRAIL(context)}"
        if context.role_variant == "script":
            duration = context.explicit_controls.get("duration_seconds")
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not 1 <= float(duration) <= 3_600
            ):
                raise _error(
                    "production_duration_required",
                    "Canonical production duration is required before Script preparation.",
                )
            duration_text = f"{float(duration):g}"
            prompt = f"{prompt}\nCanonical production duration: exactly {duration_text} seconds."
        policy_negative = " ".join(policy.negative_clauses)
        if policy_negative and policy_negative not in negative:
            negative = f"{negative} {policy_negative}".strip()
        structured = _structured_content(concrete_brief, context)
        if conditioning_plan is not None and isinstance(structured.get("style"), dict):
            structured = {
                **structured,
                "style": {
                    **structured["style"],
                    "style_prompt": "Selected reference visual style governs protected dimensions.",
                    "source": "references",
                },
            }
        if style_authority is not None:
            structured = {
                **structured,
                "reference_style_policy": style_authority.model_dump(mode="json"),
            }
        context_payload = context.model_dump(mode="json")
        references = tuple(item.reference_purpose for item in context.bindings)
        context_digest = _digest(context_payload)
        reference_digest = _digest([item.model_dump(mode="json") for item in context.bindings])
        style_digest = _digest(
            structured.get("style", context.style_projection or "")
            if context.role_variant == "video_segment"
            else (
                {
                    "projection": context.style_projection or "",
                    "reference_style_policy": style_authority.model_dump(mode="json")
                    if style_authority is not None
                    else None,
                }
            )
        )
        prompt_digest = _digest({"prompt": prompt, "negative_prompt": negative})
        prepared_prompt_digest = sha256(prompt.encode("utf-8")).hexdigest()
        sequence_value = context.storyboard_parameters.get("sequence_id")
        sequence_id = sequence_value if isinstance(sequence_value, str) else None
        available_purposes = {item.reference_purpose for item in context.bindings}
        if not set(policy.required_reference_purposes) <= available_purposes:
            raise _error(
                "node_prompt_assertion_contract_invalid",
                "Required prompt assertion reference authority is missing.",
            )
        if not set(policy.required_document_kinds) <= set(context.document_revisions):
            raise _error(
                "node_prompt_assertion_contract_invalid",
                "Required prompt assertion document authority is missing.",
            )
        if policy.required_document_kinds and not context.storyboard_parameters.get(
            "storyboard_production_plan_id"
        ):
            raise _error(
                "node_prompt_assertion_contract_invalid",
                "Required prompt assertion document identity is missing.",
            )
        if policy.sequence_scoped and not sequence_id:
            raise _error(
                "node_prompt_assertion_contract_invalid",
                "Sequence-scoped prompt assertion authority is missing.",
            )
        if policy.sequence_scoped and any(
            item.reference_purpose == "storyboard_grid" and item.source_sequence_id != sequence_id
            for item in context.bindings
        ):
            raise _error(
                "node_prompt_assertion_contract_invalid",
                "Storyboard Grid sequence does not match the target Video sequence.",
            )
        assertion_evidence = PromptAssertionEvidenceV1.build(
            policy_ref=policy.policy_ref,
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            recipe_id=recipe.recipe_id,
            recipe_version=recipe.recipe_version,
            assertion_ids=policy.assertion_ids,
            assertion_block_digest=policy.assertion_block_digest,
            prepared_prompt_digest=prepared_prompt_digest,
            source_snapshots=source_snapshots_from_context(context),
            document_revisions=context.document_revisions,
            sequence_id=sequence_id,
            engine_owned_fields_digest=policy.engine_owned_fields_digest,
        )
        return CompiledNodePromptV2(
            role_variant=context.role_variant,
            recipe_id=recipe.recipe_id,
            recipe_version=recipe.recipe_version,
            recipe_digest=recipe.recipe_digest,
            context_digest=context_digest,
            reference_bundle_digest=reference_digest,
            style_projection_digest=style_digest,
            brief_digest=brief_digest,
            prompt_digest=prompt_digest,
            prompt=prompt,
            negative_prompt=negative,
            structured_content=structured,
            parameters=parameters,
            reference_purposes=references,
            role_reference_policy_version=(
                role_policy.policy_version if role_policy is not None else None
            ),
            reference_conditioning_plan=(
                conditioning_plan.model_dump(mode="json") if conditioning_plan is not None else None
            ),
            assertion_evidence=assertion_evidence,
            compaction_policy_version=recipe.compaction_policy.policy_version,
            compaction_policy_digest=recipe.compaction_policy.digest,
            compaction_decisions=compaction_decisions,
        )

    @staticmethod
    def _validate_required_references(
        required: tuple[str, ...],
        context: RolePromptPreparationContextV2,
    ) -> None:
        available = {item.reference_purpose for item in context.bindings}
        for purpose in required:
            if purpose == "identity_reference":
                continue
            if purpose not in available:
                raise _error(
                    "node_prompt_required_reference_missing",
                    "A required exact role reference is missing.",
                )


def _render(brief: RoleCreativeBriefMemberV2) -> tuple[str, str]:
    if isinstance(brief, WorldViewRoleBriefV2):
        return (
            f"World premise: {brief.premise} Era and place: {brief.era_and_place}. "
            f"World rules: {'; '.join(brief.world_rules)}. Visual continuity: "
            f"{'; '.join(brief.visual_continuity)}.",
            "No complete script, shot list, provider syntax, or hidden topology.",
        )
    if isinstance(brief, ProductMultiviewRoleBriefV2):
        return (
            f"Use the exact bound Product Main as identity authority. Preserve {brief.identity}; "
            f"geometry: {brief.geometry}; materials: {brief.materials}; marks: {brief.marks}; "
            f"palette: {brief.palette}. Render {', '.join(brief.views)} on a clean neutral "
            "studio background.",
            "No people, hands, active use, application scene, unrelated prop, labels, captions, "
            "storyboard layout, or Product Main prompt reuse.",
        )
    if isinstance(brief, ProductMainRoleBriefV2):
        return (
            f"Create one isolated product identity on a clean neutral studio background. "
            f"Identity: {brief.identity}. Geometry: {brief.geometry}. Materials: "
            f"{brief.materials}. Brand marks: {brief.marks}. Palette: {brief.palette}.",
            "No people, hands, active use, application scene, narrative environment, accessory "
            "clutter, unrelated props, labels, captions, or storyboard layout.",
        )
    if isinstance(brief, PropRoleBriefV2):
        return (
            f"Create one isolated prop on a clean neutral studio background. Identity: "
            f"{brief.identity}. Form: {brief.form}. Materials: {brief.materials}. Palette: "
            f"{brief.palette}.",
            "No people, products, active scene, unrelated objects, text, labels, or board layout.",
        )
    if isinstance(brief, CharacterTurnaroundRoleBriefV2):
        return (
            "Use the exact bound Character Main as identity authority. Create the same detailed "
            "non-photorealistic semi-realistic commercial illustration in front, side, and back "
            "full-body views on a clean neutral background. Preserve all distinguishing details. "
            f"Identity: {brief.identity}. Face and hair: {brief.face_and_hair}. Proportions: "
            f"{brief.silhouette_and_proportions}. Wardrobe: {brief.wardrobe}. Accessories: "
            f"{brief.accessories}.",
            "No photorealistic human, identity drift, labels, captions, annotation text, product, "
            "prop, active scene, unrelated reference, second person, or alternate wardrobe.",
        )
    if isinstance(brief, CharacterMainRoleBriefV2):
        return (
            "Create exactly one full-body detailed semi-realistic commercial "
            f"illustration on a clean neutral background. Preserve all distinguishing details. "
            f"Identity: {brief.identity}. Face and hair: "
            f"{brief.face_and_hair}. Silhouette and proportions: "
            f"{brief.silhouette_and_proportions}. Wardrobe: {brief.wardrobe}. Accessories: "
            f"{brief.accessories}.",
            "No photograph, photorealistic human, product, prop, active scene, second person, "
            "text, labels, annotation, captions, or board layout.",
        )
    if isinstance(brief, SceneBoardRoleBriefV2):
        return (
            "Create one text-free 3x3 environment board of the same coherent environment. "
            f"Identity: {brief.environment_identity}. Spatial logic: {brief.spatial_logic}. "
            f"Lighting: {brief.lighting}. Materials: {brief.materials}. Atmosphere: "
            f"{brief.atmosphere}. Views: {'; '.join(brief.views)}.",
            "No active character, product, prop interaction, narrative action, plot progression, "
            "captions, labels, panel numbers, or unrelated environment.",
        )
    if isinstance(brief, ScriptRoleBriefV2):
        return (
            f"Editable narrative: {brief.narrative}. Timing: {brief.timing}. Dialogue: "
            f"{brief.dialogue}. Voiceover: {brief.voiceover}.",
            "No provider rendering syntax or final shot-grid layout.",
        )
    if isinstance(brief, StoryboardGridRoleBriefV2):
        return (
            "Create one complete text-free 3x3 Storyboard Sequence with exactly nine ordered "
            f"visual beats. Sequence: {brief.sequence_summary}. Beats: "
            f"{'; '.join(brief.beats)}. Visual language: {brief.visual_language}.",
            "No captions, labels, panel numbers, speech bubbles, provider prompt reuse, or beats "
            "from another Sequence.",
        )
    if isinstance(brief, VideoSegmentRoleBriefV2):
        return (
            f"Create one {brief.duration_seconds:g}-second video segment. "
            f"{brief.segment_summary} Action: {brief.action}. Dialogue: {brief.dialogue}. "
            f"Voiceover: {brief.voiceover}. Ambience: {brief.ambience}. Synchronized action "
            f"effects: {brief.action_effects}. Target output style: {brief.target_style}.",
            "No background music, identity drift, unrelated action, or visible text.",
        )
    if isinstance(brief, BgmRoleBriefV2):
        return (
            f"Create pure instrumental advertising music for {brief.duration_seconds:g} seconds. "
            f"{brief.music_summary} Pace: {brief.pace}. Energy curve: {brief.energy_curve}. "
            f"Instrumentation: {brief.instrumentation}. Mood: {brief.mood}.",
            "No vocals, lyrics, speech, dialogue, voiceover, ambience, or action effects.",
        )
    if isinstance(brief, FreeMediaRoleBriefV2):
        return brief.prompt, "No undeclared identities, references, or hidden context."
    raise _error("node_prompt_brief_invalid", "Role brief is unsupported.")


def _structured_content(
    brief: RoleCreativeBriefMemberV2,
    context: RolePromptPreparationContextV2,
) -> dict[str, object]:
    style = VisualStyleContractV2(
        style_prompt=(
            context.style_projection or "Detailed semi-realistic advertising illustration"
        ),
        source="video_skill" if context.style_projection else "platform_default",
    )
    if isinstance(brief, WorldViewRoleBriefV2):
        content = (
            f"{brief.premise}\n\nEra and place: {brief.era_and_place}\n"
            f"World rules: {'; '.join(brief.world_rules)}\n"
            f"Visual continuity: {'; '.join(brief.visual_continuity)}"
        )
        return WorldSettingDocumentV2(
            content=content,
            core=WorldSettingCoreV2(
                premise=brief.premise,
                era_and_place=brief.era_and_place,
                world_rules=brief.world_rules,
                visual_continuity=brief.visual_continuity,
            ),
            authoring_provenance=WorldSettingAuthoringProvenanceV2(
                source_proposal_id=context.requirement_revision_id,
                source_option_id=context.node_id,
                materialization_run_id=(f"role-prompt:{context.node_id}:{context.node_revision}"),
            ),
        ).model_dump(mode="json")
    if isinstance(brief, ProductMultiviewRoleBriefV2):
        return DesignAssetContentV2(
            asset_kind="multi_view",
            subject_identity=brief.identity,
            design_summary="; ".join((brief.geometry, brief.materials, brief.marks, brief.palette)),
            style=style,
            explicit_inclusions=brief.views,
            negative_constraints=("application scene", "main prompt reuse", "text"),
        ).model_dump(mode="json")
    if isinstance(brief, ProductMainRoleBriefV2):
        return DesignAssetContentV2(
            asset_kind="main",
            subject_identity=brief.identity,
            design_summary="; ".join((brief.geometry, brief.materials, brief.marks, brief.palette)),
            style=style,
            negative_constraints=("people", "application scene", "text"),
        ).model_dump(mode="json")
    if isinstance(brief, PropRoleBriefV2):
        return DesignAssetContentV2(
            subject_identity=brief.identity,
            design_summary="; ".join((brief.form, brief.materials, brief.palette)),
            style=style,
            negative_constraints=("people", "products", "active scene", "text"),
        ).model_dump(mode="json")
    if isinstance(brief, CharacterTurnaroundRoleBriefV2):
        return CharacterDesignAssetContentV2(
            subject_identity=brief.identity,
            design_summary="; ".join(
                (
                    brief.face_and_hair,
                    brief.silhouette_and_proportions,
                    brief.wardrobe,
                    brief.accessories,
                )
            ),
            style=style,
            explicit_inclusions=brief.views,
            negative_constraints=("photorealistic human", "text", "identity drift"),
            character_asset_kind="turnaround",
        ).model_dump(mode="json")
    if isinstance(brief, CharacterMainRoleBriefV2):
        return CharacterDesignAssetContentV2(
            subject_identity=brief.identity,
            design_summary="; ".join(
                (
                    brief.face_and_hair,
                    brief.silhouette_and_proportions,
                    brief.wardrobe,
                    brief.accessories,
                )
            ),
            style=style,
            negative_constraints=("photorealistic human", "text", "identity drift"),
            character_asset_kind="identity_master",
        ).model_dump(mode="json")
    if isinstance(brief, SceneBoardRoleBriefV2):
        panels = tuple(
            SceneBoardPanelV2(
                panel_index=index,
                view_or_zone=view,
                spatial_description=f"{brief.spatial_logic} View: {view}.",
                lighting_material_detail=f"{brief.lighting} {brief.materials}",
            )
            for index, view in enumerate(brief.views, start=1)
        )
        return SceneDesignBoardContentV2(
            scene_identity=brief.environment_identity,
            environment_summary=f"{brief.spatial_logic} {brief.atmosphere}",
            layout="Nine distinct views of one coherent environment.",
            lighting=brief.lighting,
            materials=brief.materials,
            time_of_day="Use the accepted scene time of day.",
            style=style,
            panels=panels,
        ).model_dump(mode="json")
    if isinstance(brief, ScriptRoleBriefV2):
        return {
            "content": (
                f"{brief.narrative}\n\nTiming: {brief.timing}\n"
                f"Dialogue: {brief.dialogue}\nVoiceover: {brief.voiceover}"
            )
        }
    if isinstance(brief, StoryboardGridRoleBriefV2):
        panels = tuple(
            StoryboardPanelV2(
                panel_index=index,
                beat=beat,
                composition=f"Composition for ordered beat {index}.",
                camera=f"Camera setup for ordered beat {index}.",
                subject_action=beat,
                continuity_from_previous=(
                    "Opening state." if index == 1 else f"Continue from beat {index - 1}."
                ),
            )
            for index, beat in enumerate(brief.beats, start=1)
        )
        return StoryboardGridContentV2(
            sequence_summary=brief.sequence_summary,
            narrative_goal=brief.sequence_summary,
            style=style,
            panels=panels,
        ).model_dump(mode="json")
    if isinstance(brief, VideoSegmentRoleBriefV2):
        return VideoSegmentContentV2(
            segment_summary=brief.segment_summary,
            duration_seconds=brief.duration_seconds,
            storyboard_content=brief.action,
            representation_mode=(context.video_representation_mode or "illustrated"),
            style=style,
            dialogue=brief.dialogue,
            voice_style=brief.voiceover,
            environment_sound=brief.ambience,
            action_effects=brief.action_effects,
            negative_constraints="No background music or identity drift.",
        ).model_dump(mode="json")
    if isinstance(brief, BgmRoleBriefV2):
        return BgmContentV2(
            music_summary=brief.music_summary,
            duration_seconds=brief.duration_seconds,
            pace=brief.pace,
            energy_curve=brief.energy_curve,
            instrumentation=brief.instrumentation,
            mood=brief.mood,
        ).model_dump(mode="json")
    if isinstance(brief, FreeMediaRoleBriefV2):
        content: dict[str, object] = {"prompt": brief.prompt}
        if brief.role_variant == "free_video":
            content["background_music"] = False
        return content
    raise _error("node_prompt_brief_invalid", "Role brief is unsupported.")


def _LIVE_ACTION_IDENTITY_GUARDRAIL(context: RolePromptPreparationContextV2) -> str:
    """Append immutable illustration identity constraints after advisory style text."""

    facts: list[str] = []
    for binding in context.bindings:
        if binding.source_role != "character" or binding.character_phase != "turnaround":
            continue
        identity = "exact current Character Turnaround AssetVersion"
        if binding.occurrence_id:
            identity += f" for occurrence {binding.occurrence_id}"
        facts.append(identity)
    references = "; ".join(facts) or "each bound Character Turnaround AssetVersion"
    return (
        "Render fictional cinematic live action from the detailed illustration references. "
        f"Use {references} as strict identity and design authority. Preserve character count, "
        "occurrence mapping, age band, face and design cues, body proportions, overall model, "
        "silhouette, hair shape and color, wardrobe construction, fit, colors, patterns, "
        "materials, footwear, accessories, and markings. Only rendering medium, linework, "
        "shading, photographic texture, lens, lighting, and color grading may drift. Do not "
        "redesign, substitute wardrobe, change clothing colors/patterns/materials, change body "
        "shape or model, merge, duplicate, or swap occurrences. These identity constraints are "
        "the final instruction and override advisory style guidance."
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _validate_role_prompt_text(role_variant: str, text: str) -> None:
    normalized = text.casefold()
    for phrase in _ROLE_PROMPT_CONFLICTS.get(role_variant, ()):
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])")
        if any(
            not _is_explicitly_negated(normalized, match.start())
            for match in pattern.finditer(normalized)
        ):
            raise _error(
                "node_prompt_role_contract_invalid",
                "Role prompt text conflicts with the foundation isolation contract.",
            )


_NEGATED_ROLE_CONFLICT = re.compile(
    r"(?:^|[\s,(])(?:no|without|not|never|do not|does not|must not)"
    r"(?:\s+[a-z0-9-]+){0,3}\s*,?\s*$"
)


def _is_explicitly_negated(text: str, position: int) -> bool:
    """Keep negative role facts separate from instructions to add a conflict."""

    clause_start = max(
        text.rfind(delimiter, 0, position) for delimiter in (".", "!", "?", ";", ":", "\n")
    )
    return _NEGATED_ROLE_CONFLICT.search(text[clause_start + 1 : position]) is not None


def _compaction_decisions(
    context: RolePromptPreparationContextV2,
    recipe,
    *,
    brief_digest: str,
) -> tuple[RolePromptCompactionDecisionV2, ...]:
    """Apply only an explicit, digest-backed compiler duplicate proof."""

    retained_brief_id = f"role_brief:{brief_digest}"
    decisions: list[RolePromptCompactionDecisionV2] = []
    for block in context.context_blocks:
        reason = "preserved_authority"
        outcome = "preserved"
        if not recipe.compaction_policy.enabled:
            reason = "policy_disabled"
        elif block.source_kind not in recipe.compaction_policy.eligible_source_kinds:
            reason = "not_eligible"
        elif block.ownership != "compiler":
            reason = "ownership_unknown"
        elif (
            block.disposition != "duplicate_candidate"
            or block.retained_block_id != retained_brief_id
            or block.retained_precedence != block.precedence
            or block.source_digest != brief_digest
            or block.effective_constraints_digest != brief_digest
        ):
            reason = "identity_unproven"
        else:
            reason = "exact_duplicate"
            outcome = "compacted"
        decisions.append(
            RolePromptCompactionDecisionV2(
                block_id=block.block_id,
                source_id=block.source_id,
                source_digest=block.source_digest,
                precedence=block.precedence,
                outcome=outcome,  # type: ignore[arg-type]
                retained_block_id=block.retained_block_id,
                retained_precedence=block.retained_precedence,
                reason=reason,  # type: ignore[arg-type]
            )
        )
    return tuple(decisions)


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_role_prompt_compiler")
