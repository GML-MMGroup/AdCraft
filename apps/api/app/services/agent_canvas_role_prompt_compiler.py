"""Deterministic compiler for typed Agent Canvas role briefs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import logging
import re
from typing import TYPE_CHECKING
from pydantic import ValidationError

if TYPE_CHECKING:
    from app.schemas.agent_canvas import CanvasNodeV2

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_errors import ActionableFailureV1
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
    CharacterIdentityAuthorityProjectionV1,
    CompiledNodePromptV2,
    FreeMediaRoleBriefV2,
    ProductMainRoleBriefV2,
    ProductMultiviewRoleBriefV2,
    ProductIdentityAuthorityProjectionV1,
    PropRoleBriefV2,
    RolePromptCompactionDecisionV2,
    ResolvedNodeParameterV2,
    RoleCreativeBriefV2,
    RoleCreativeBriefMemberV2,
    RolePromptPreparationContextV2,
    RolePromptViolationV1,
    SceneEnvironmentViewV1,
    SceneBoardRoleBriefV2,
    SceneEnvironmentProjectionV1,
    ScriptRoleBriefV2,
    StoryboardGridRoleBriefV2,
    VideoSegmentRoleBriefV2,
    WorldViewRoleBriefV2,
)
from app.services.agent_canvas_human_style_rules import human_style_rule
from app.services.agent_canvas_prompt_assertion_policy import (
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


logger = logging.getLogger(__name__)


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
    "character_main": (),
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
    "video_segment": (
        "background music",
        "bgm",
        "soundtrack",
        "music",
    ),
}
_SCENE_CONFLICT_CATEGORIES = {
    "character": "positive_character",
    "characters": "positive_character",
    "active character": "positive_character",
    "product": "positive_product",
    "products": "positive_product",
    "prop": "positive_prop",
    "props": "positive_prop",
    "narrative action": "narrative_progression",
    "plot progression": "narrative_progression",
}


@dataclass(frozen=True)
class RolePromptCompilationResult:
    """Python-only compilation artifacts; projections never enter the sidecar contract."""

    compiled_prompt: CompiledNodePromptV2
    scene_environment_projection: SceneEnvironmentProjectionV1 | None


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
        editable_prompt_override: str | None = None,
        preserved_node: CanvasNodeV2 | None = None,
    ) -> CompiledNodePromptV2:
        return self.compile_with_projections(
            brief,
            context,
            parameters=parameters,
            editable_prompt_override=editable_prompt_override,
            preserved_node=preserved_node,
        ).compiled_prompt

    def compile_with_projections(
        self,
        brief: RoleCreativeBriefV2 | RoleCreativeBriefMemberV2,
        context: RolePromptPreparationContextV2,
        *,
        parameters: tuple[ResolvedNodeParameterV2, ...] = (),
        editable_prompt_override: str | None = None,
        preserved_node: CanvasNodeV2 | None = None,
    ) -> RolePromptCompilationResult:
        """Return the exact semantic authority used by the compiled prompt and evidence."""

        concrete_brief = brief.root if isinstance(brief, RoleCreativeBriefV2) else brief
        if concrete_brief.role_variant != context.role_variant:
            raise _error("node_prompt_brief_invalid", "Role brief variant does not match context.")
        recipe = self._registry.resolve(context.role_variant)
        policy = self._assertion_policies.resolve_for_video_audio(
            recipe.recipe_id,
            recipe.recipe_version,
            policy_version=(
                preserved_node.prompt_preparation.assertion_evidence.policy_version
                if preserved_node is not None
                and preserved_node.prompt_preparation.assertion_evidence is not None
                else None
            ),
            native_audio_required=(
                context.role_variant == "video_segment"
                and any(item.name == "generate_audio" and item.value is True for item in parameters)
            ),
            allows_comedic_sound_effects=(
                context.style_expression is not None
                and context.style_expression.allows_comedic_sound_effects
            ),
            scene_asset_kind=(
                context.node_parameters.get("scene_asset_kind")
                if context.role_variant == "scene_board"
                else None
            ),
        )
        role_policy = self._reference_policy.for_prompt_variant(context.role_variant)
        brief_payload = concrete_brief.model_dump(mode="json")
        brief_digest = _digest(brief_payload)
        compaction_decisions = _compaction_decisions(
            context,
            recipe,
            brief_digest=brief_digest,
        )
        character_projection, scene_projection, product_projection = _semantic_projections(
            concrete_brief,
            context,
        )
        rendered_prompt, negative = _render(
            concrete_brief,
            scene_multiview=(
                context.role_variant == "scene_board"
                and context.node_parameters.get("scene_asset_kind") == "multi_view"
            ),
            character_projection=character_projection,
            scene_projection=scene_projection,
            product_projection=product_projection,
        )
        editable_prompt = (
            editable_prompt_override
            if editable_prompt_override is not None
            else concrete_brief.editable_prompt
        )
        if editable_prompt is not None:
            prompt = editable_prompt.strip()
            if not prompt:
                raise _error(
                    "node_prompt_brief_invalid",
                    "Editable prompt must not be blank.",
                )
        else:
            prompt = rendered_prompt
        if (
            editable_prompt is not None
            and editable_prompt_override is None
            and isinstance(
                concrete_brief,
                (
                    ProductMainRoleBriefV2,
                    PropRoleBriefV2,
                    CharacterMainRoleBriefV2,
                    SceneBoardRoleBriefV2,
                ),
            )
        ):
            prompt += (
                "\n\nReference identity and output format (preserve authored presentation): "
                + rendered_prompt
            )
        if isinstance(concrete_brief, VideoSegmentRoleBriefV2) and editable_prompt_override is None:
            prompt = _retain_video_audio(prompt, concrete_brief)
        _validate_role_prompt_text(
            context.role_variant,
            prompt,
            field_path=("editable_prompt" if editable_prompt is not None else "rendered_prompt"),
            node_id=context.node_id,
            workflow_id=context.workflow_id,
        )
        style_authority = ReferenceStyleAuthorityPolicyResolver().resolve(context)
        conditioning_plan = ReferenceConditioningPlanResolver().resolve(context)
        authored_style = _authored_visual_style(concrete_brief)
        if style_authority is not None:
            prompt = ReferenceAwareAssetPromptRenderer().render(
                prompt,
                authored_style,
                style_authority,
                explicit_controls=context.explicit_controls,
                conditioning_plan=conditioning_plan,
            )
        else:
            # Advisory Skill text is available to the Agent authoring call, while
            # provider content is taken from the typed role brief it produced.
            if context.style_projection and not isinstance(concrete_brief, VideoSegmentRoleBriefV2):
                _validate_role_prompt_text(
                    context.role_variant,
                    context.style_projection,
                    field_path="style_projection",
                    node_id=context.node_id,
                    workflow_id=context.workflow_id,
                )
            if authored_style:
                _validate_role_prompt_text(
                    context.role_variant,
                    authored_style,
                    field_path="style_description",
                    node_id=context.node_id,
                    workflow_id=context.workflow_id,
                )
                prompt = f"{prompt} Visual style: {authored_style.strip()}"
        required_references = recipe.reference_purposes
        if (
            context.role_variant == "scene_board"
            and context.node_parameters.get("scene_asset_kind") == "multi_view"
        ):
            matching = tuple(
                item for item in context.bindings if item.reference_purpose == "scene_main_identity"
            )
            scene_sources = tuple(item for item in context.bindings if item.source_role == "scene")
            if len(matching) != 1 or matching[0].source_role != "scene" or len(scene_sources) != 1:
                raise _error(
                    "node_prompt_required_reference_missing",
                    "Scene Multi-view requires the sole bound Scene Main identity source.",
                )
            required_references = ("scene_main_identity",)
        self._validate_required_references(required_references, context)
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
        rule = human_style_rule(
            concrete_brief if isinstance(concrete_brief, CharacterMainRoleBriefV2) else context
        )
        if rule is not None:
            # User decision (2026-10-26): the rule is visible in the node prompt.
            prompt = f"{prompt}\n\n{rule}"
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
        structured = _structured_content(
            concrete_brief,
            context,
            scene_projection=scene_projection,
            product_projection=product_projection,
        )
        if (
            conditioning_plan is not None
            and not authored_style
            and isinstance(structured.get("style"), dict)
        ):
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
        if preserved_node is not None:
            presentation = preserved_node.prompt_presentation
            saved_prompt = preserved_node.generation_prompt
            if (
                context.role_variant
                not in {
                    "storyboard_grid",
                    "video_segment",
                    "character_turnaround",
                    "product_multiview",
                }
                and not (
                    context.role_variant == "scene_board"
                    and context.node_parameters.get("scene_asset_kind") == "multi_view"
                )
                or presentation is None
                or presentation.brief_digest is None
                or presentation.source not in {"agent_authored", "deterministic_projection"}
                or not saved_prompt
                or presentation.text != saved_prompt
                or presentation.prompt_digest
                != f"sha256:{sha256(saved_prompt.encode('utf-8')).hexdigest()}"
                or saved_prompt.count(policy.assertion_block) != 1
            ):
                raise _error(
                    "node_prompt_assertion_contract_invalid",
                    "Saved creative prompt authority is invalid.",
                )
            content_model = (
                StoryboardGridContentV2
                if context.role_variant == "storyboard_grid"
                else CharacterDesignAssetContentV2
                if context.role_variant == "character_turnaround"
                else DesignAssetContentV2
                if context.role_variant == "product_multiview"
                else SceneDesignBoardContentV2
                if context.role_variant == "scene_board"
                else VideoSegmentContentV2
            )
            try:
                saved_content = content_model.model_validate(
                    preserved_node.structured_content
                ).model_dump(mode="json")
                if context.role_variant == "character_turnaround":
                    for key in (
                        "parent_source_node_id",
                        "parent_source_node_revision",
                        "parent_asset_version_id",
                        "identity_projection_digest",
                    ):
                        saved_content[key] = structured[key]
                elif context.role_variant == "scene_board":
                    if context.scene_environment_projection is not None:
                        saved_content["environment_projection_digest"] = (
                            context.scene_environment_projection.projection_digest
                        )
                structured = saved_content
            except ValidationError as error:
                raise _error(
                    "node_prompt_brief_invalid", "Saved creative structured content is invalid."
                ) from error
            prompt = saved_prompt
            brief_digest = presentation.brief_digest
            compaction_decisions = ()
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
            character_identity_projection_digest=(
                character_projection.projection_digest if character_projection is not None else None
            ),
            scene_environment_projection_digest=(
                scene_projection.projection_digest if scene_projection is not None else None
            ),
            engine_owned_fields_digest=policy.engine_owned_fields_digest,
        )
        compiled_prompt = CompiledNodePromptV2(
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
            editable_prompt=editable_prompt,
            negative_prompt=negative,
            structured_content=structured,
            parameters=parameters,
            reference_purposes=references,
            role_reference_policy_version=(
                role_policy.policy_version if role_policy is not None else None
            ),
            reference_conditioning_plan=(
                conditioning_plan if conditioning_plan is not None else None
            ),
            assertion_evidence=assertion_evidence,
            compaction_policy_version=recipe.compaction_policy.policy_version,
            compaction_policy_digest=recipe.compaction_policy.digest,
            compaction_decisions=compaction_decisions,
        )
        return RolePromptCompilationResult(
            compiled_prompt=compiled_prompt,
            scene_environment_projection=scene_projection,
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


def _semantic_projections(
    brief: RoleCreativeBriefMemberV2,
    context: RolePromptPreparationContextV2,
) -> tuple[
    CharacterIdentityAuthorityProjectionV1 | None,
    SceneEnvironmentProjectionV1 | None,
    ProductIdentityAuthorityProjectionV1 | None,
]:
    if isinstance(brief, CharacterTurnaroundRoleBriefV2):
        projection = context.character_identity_projection
        if projection is not None:
            if not context.bindings:
                raise _error(
                    "character_parent_identity_projection_invalid",
                    "Character Turnaround requires a current Main Binding.",
                )
            parent = context.bindings[0]
            if (
                parent.source_node_id != projection.source_node_id
                or parent.source_node_revision != projection.source_node_revision
                or parent.asset_id != projection.source_asset_id
                or parent.asset_version_id != projection.source_asset_version_id
                or parent.occurrence_id != projection.occurrence_id
                or parent.character_phase != "main"
            ):
                raise _error(
                    "character_parent_identity_projection_invalid",
                    "Character Main projection is stale or not the exact bound occurrence.",
                )
            protected = {
                "identity": projection.identity,
                "face_and_hair": projection.face_and_hair,
                "silhouette_and_proportions": projection.silhouette_and_proportions,
                "wardrobe": projection.wardrobe,
                "accessories": projection.accessories,
                "rendering_mode": projection.rendering_mode,
                "gender_presentation": projection.gender_presentation,
                "human_face": projection.human_face,
            }
            for name, expected in protected.items():
                actual = getattr(brief, name)
                if actual not in {"", "unspecified"} and actual != expected:
                    raise _error(
                        "character_turnaround_identity_conflict",
                        "Turnaround identity differs from the bound Character Main authority.",
                    )
            return projection, None, None
        return None, None, None
    if isinstance(brief, CharacterMainRoleBriefV2):
        projection = context.character_identity_projection
        if projection is not None and projection.occurrence_id != context.occurrence_id:
            raise _error(
                "character_parent_identity_projection_invalid",
                "Character Main projection occurrence is stale.",
            )
        return projection, None, None
    if isinstance(brief, SceneBoardRoleBriefV2):
        projection = context.scene_environment_projection
        if projection is None:
            from app.schemas.agent_canvas_role_prompt_preparation import SceneEnvironmentViewV1

            projection = SceneEnvironmentProjectionV1.build(
                source_node_id=context.node_id,
                source_node_revision=context.node_revision,
                environment_identity=brief.environment_identity,
                spatial_logic=brief.spatial_logic,
                lighting=brief.lighting,
                materials=brief.materials,
                atmosphere=brief.atmosphere,
                views=tuple(
                    SceneEnvironmentViewV1(
                        view_or_zone=view,
                        spatial_details=f"{brief.spatial_logic} View: {view}.",
                        allowed_environment_elements=(),
                    )
                    for view in brief.views
                ),
                entity_references=brief.entity_references,
                action_references=brief.action_references,
                environment_only=brief.environment_only,
            )
        if projection.entity_references or projection.action_references:
            raise _error(
                "scene_environment_projection_invalid",
                "Scene preparation requires an environment-only projection.",
            )
        if context.node_parameters.get("scene_asset_kind") == "multi_view":
            parent_bindings = tuple(
                item for item in context.bindings if item.reference_purpose == "scene_main_identity"
            )
            if len(parent_bindings) != 1:
                raise _error(
                    "scene_parent_environment_projection_invalid",
                    "Scene Multi-view requires one exact Scene Main authority.",
                )
            parent = parent_bindings[0]
            if (
                parent.source_role != "scene"
                or parent.reference_purpose != "scene_main_identity"
                or parent.source_node_id != projection.source_node_id
            ):
                raise _error(
                    "scene_parent_environment_projection_invalid",
                    "Scene Main projection is stale or not the exact bound authority.",
                )
        if (
            projection.source_node_revision != context.node_revision
            and context.node_id == projection.source_node_id
        ):
            raise _error(
                "node_prompt_context_stale",
                "Scene environment projection revision is stale.",
            )
        return None, projection, None
    if isinstance(brief, ProductMultiviewRoleBriefV2):
        projection = context.product_identity_projection
        if projection is not None:
            parent_bindings = tuple(
                item
                for item in context.bindings
                if item.reference_purpose == "product_main_identity"
            )
            if len(parent_bindings) != 1:
                raise _error(
                    "product_parent_identity_projection_invalid",
                    "Product Multi-view projection requires one exact Product Main authority.",
                )
            parent = parent_bindings[0]
            if (
                parent.source_role != "product"
                or parent.source_node_id != projection.source_node_id
                or parent.source_node_revision != projection.source_node_revision
            ):
                raise _error(
                    "product_parent_identity_projection_invalid",
                    "Product Main projection is stale or not the exact bound authority.",
                )
        return None, None, projection
    return None, None, None


def _render(
    brief: RoleCreativeBriefMemberV2,
    *,
    scene_multiview: bool = False,
    character_projection: CharacterIdentityAuthorityProjectionV1 | None = None,
    scene_projection: SceneEnvironmentProjectionV1 | None = None,
    product_projection: ProductIdentityAuthorityProjectionV1 | None = None,
) -> tuple[str, str]:
    if isinstance(brief, WorldViewRoleBriefV2):
        return (
            f"World premise: {brief.premise} Era and place: {brief.era_and_place}. "
            f"World rules: {'; '.join(brief.world_rules)}. Visual continuity: "
            f"{'; '.join(brief.visual_continuity)}.",
            "No complete script, shot list, provider syntax, or hidden topology.",
        )
    if isinstance(brief, ProductMultiviewRoleBriefV2):
        identity = product_projection.subject_identity if product_projection else brief.identity
        design_summary = (
            product_projection.design_summary
            if product_projection
            else "; ".join((brief.geometry, brief.materials, brief.marks, brief.palette))
        )
        return (
            f"Use the exact bound Product Main as identity authority. Preserve {identity}; "
            f"{design_summary}. Render {', '.join(brief.views)} on a clean neutral "
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
        identity = character_projection.identity if character_projection else brief.identity
        face_and_hair = (
            character_projection.face_and_hair if character_projection else brief.face_and_hair
        )
        silhouette = (
            character_projection.silhouette_and_proportions
            if character_projection
            else brief.silhouette_and_proportions
        )
        wardrobe = character_projection.wardrobe if character_projection else brief.wardrobe
        accessories = (
            character_projection.accessories if character_projection else brief.accessories
        )
        return (
            "Use the exact bound Character Main as identity authority. Create the same "
            "character in the selected visual style, matching the bound Main's rendering "
            "treatment, in front, side, and back "
            "full-body views on a clean neutral background. Preserve all distinguishing details. "
            f"Identity: {identity}. Face and hair: {face_and_hair}. Proportions: "
            f"{silhouette}. Wardrobe: {wardrobe}."
            f"{_optional_labeled_fragment('Accessories', accessories)}",
            "No identity drift, labels, captions, annotation text, product, "
            "prop, active scene, unrelated reference, second person, or alternate wardrobe.",
        )
    if isinstance(brief, CharacterMainRoleBriefV2):
        return (
            "Create exactly one full-body character reference in the selected visual style "
            "on a clean neutral background. "
            "Preserve all distinguishing details. "
            f"Identity: {brief.identity}. Face and hair: "
            f"{brief.face_and_hair}. Silhouette and proportions: "
            f"{brief.silhouette_and_proportions}. Wardrobe: {brief.wardrobe}."
            f"{_optional_labeled_fragment('Accessories', brief.accessories)}",
            "No product, prop, active scene, second character, "
            "text, labels, annotation, captions, or board layout.",
        )
    if isinstance(brief, SceneBoardRoleBriefV2):
        environment_identity = (
            scene_projection.environment_identity
            if scene_projection
            else brief.environment_identity
        )
        spatial_logic = scene_projection.spatial_logic if scene_projection else brief.spatial_logic
        lighting = scene_projection.lighting if scene_projection else brief.lighting
        materials = scene_projection.materials if scene_projection else brief.materials
        atmosphere = scene_projection.atmosphere if scene_projection else brief.atmosphere
        views = (
            tuple(_scene_view_text(view) for view in _scene_views(brief)) if scene_multiview else ()
        )
        prompt = (
            (
                "Use the bound Scene Main image as the sole environment identity source. "
                "Create one text-free 3x3 grid of nine equal panels showing the same primary "
                "location from distinct viewpoints around and inside it. "
            )
            if scene_multiview
            else "Create one single full-frame image of the scene's primary location. "
        ) + (
            f"Identity: {environment_identity}. Spatial logic: {spatial_logic}. "
            f"Lighting: {lighting}. Materials: {materials}. Atmosphere: {atmosphere}."
            f"{_optional_labeled_fragment('Views', '; '.join(views))}"
        )
        negative = (
            "No other locations, people, text, captions, or narrative action."
            if scene_multiview
            else "No combined alternate views, collage, split screen, multiple locations, people, product, "
            "prop interaction, narrative action, plot progression, or text."
        )
        return prompt, negative
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
            "No background music, identity drift, or unrelated action.",
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


def _scene_views(brief: SceneBoardRoleBriefV2) -> tuple[SceneEnvironmentViewV1, ...]:
    """Keep authored camera geometry outside the bound environment identity."""
    if brief.view_plan:
        views = tuple(
            SceneEnvironmentViewV1(
                view_or_zone=view.view_or_zone,
                spatial_details=(
                    f"Camera position: {view.camera_position}. Direction: {view.camera_direction}. "
                    f"Framing: {view.framing}. Visible anchors: {'; '.join(view.visible_anchors)}. "
                    f"{view.spatial_details}"
                ),
                allowed_environment_elements=view.visible_anchors,
            )
            for view in brief.view_plan
        )
    else:
        # Historical briefs can carry complete view directions in the original field.
        views = tuple(
            SceneEnvironmentViewV1(view_or_zone=view, spatial_details=view) for view in brief.views
        )
    if len(views) != 9 or len({view.spatial_details for view in views}) != 9:
        raise _error(
            "node_prompt_brief_invalid",
            "Scene Multi-view requires nine distinct authored view directions.",
        )
    return views


def _scene_view_text(view: SceneEnvironmentViewV1) -> str:
    return f"{view.view_or_zone}: {view.spatial_details}"


def _optional_labeled_fragment(label: str, value: str) -> str:
    """Render an optional prompt field only when it contains meaningful text."""

    return f" {label}: {value}." if value.strip() else ""


def _authored_visual_style(brief: RoleCreativeBriefMemberV2) -> str | None:
    if isinstance(brief, VideoSegmentRoleBriefV2):
        return brief.target_style
    if isinstance(brief, (BgmRoleBriefV2, ScriptRoleBriefV2, WorldViewRoleBriefV2)):
        return None
    if isinstance(brief, FreeMediaRoleBriefV2) and brief.role_variant in {
        "free_audio",
        "free_text",
    }:
        return None
    return brief.style_description


def _retain_video_audio(prompt: str, brief: VideoSegmentRoleBriefV2) -> str:
    """Keep declared native audio visible without inventing or reauthoring it."""
    for label, value in (
        ("Dialogue", brief.dialogue),
        ("Voiceover", brief.voiceover),
        ("Ambience", brief.ambience),
        ("Synchronized action effects", brief.action_effects),
    ):
        text = value.strip()
        if text and text not in prompt:
            prompt = f"{prompt}\n{label}: {text}"
    return prompt


def _structured_content(
    brief: RoleCreativeBriefMemberV2,
    context: RolePromptPreparationContextV2,
    *,
    scene_projection: SceneEnvironmentProjectionV1 | None = None,
    product_projection: ProductIdentityAuthorityProjectionV1 | None = None,
) -> dict[str, object]:
    default_style = "Detailed semi-realistic advertising illustration"
    if isinstance(brief, CharacterMainRoleBriefV2):
        default_style = "Character reference in the selected visual style and bound Main treatment"
    if (
        isinstance(brief, VideoSegmentRoleBriefV2)
        and context.video_representation_mode == "illustration_to_live_action"
    ):
        default_style = "Fictional cinematic live-action with coherent lighting and materials"
    authored_style = _authored_visual_style(brief)
    style = VisualStyleContractV2(
        style_prompt=authored_style or default_style,
        source="video_skill" if authored_style else "platform_default",
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
            subject_identity=(
                product_projection.subject_identity if product_projection else brief.identity
            ),
            design_summary=(
                product_projection.design_summary
                if product_projection
                else "; ".join((brief.geometry, brief.materials, brief.marks, brief.palette))
            ),
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
        projection = context.character_identity_projection
        human_face = projection.human_face if projection is not None else brief.human_face
        return CharacterDesignAssetContentV2(
            subject_identity=projection.identity if projection is not None else brief.identity,
            face_and_hair=projection.face_and_hair
            if projection is not None
            else brief.face_and_hair,
            silhouette_and_proportions=(
                projection.silhouette_and_proportions
                if projection is not None
                else brief.silhouette_and_proportions
            ),
            wardrobe=projection.wardrobe if projection is not None else brief.wardrobe,
            accessories=projection.accessories if projection is not None else brief.accessories,
            gender_presentation=(
                projection.gender_presentation
                if projection is not None
                else brief.gender_presentation
            ),
            human_face=human_face,
            design_summary="; ".join(
                (
                    projection.face_and_hair if projection is not None else brief.face_and_hair,
                    (
                        projection.silhouette_and_proportions
                        if projection is not None
                        else brief.silhouette_and_proportions
                    ),
                    projection.wardrobe if projection is not None else brief.wardrobe,
                    projection.accessories if projection is not None else brief.accessories,
                )
            ),
            style=style,
            explicit_inclusions=brief.views,
            negative_constraints=("text", "identity drift"),
            character_asset_kind="turnaround",
            occurrence_id=context.occurrence_id,
            parent_source_node_id=(projection.source_node_id if projection is not None else None),
            parent_source_node_revision=(
                projection.source_node_revision if projection is not None else None
            ),
            parent_asset_version_id=(
                projection.source_asset_version_id if projection is not None else None
            ),
            identity_projection_digest=(
                projection.projection_digest if projection is not None else None
            ),
        ).model_dump(mode="json")
    if isinstance(brief, CharacterMainRoleBriefV2):
        return CharacterDesignAssetContentV2(
            subject_identity=brief.identity,
            face_and_hair=brief.face_and_hair,
            silhouette_and_proportions=brief.silhouette_and_proportions,
            wardrobe=brief.wardrobe,
            accessories=brief.accessories,
            gender_presentation=brief.gender_presentation,
            human_face=brief.human_face,
            design_summary="; ".join(
                (
                    brief.face_and_hair,
                    brief.silhouette_and_proportions,
                    brief.wardrobe,
                    brief.accessories,
                )
            ),
            style=style,
            negative_constraints=("text", "identity drift"),
            character_asset_kind="identity_master",
        ).model_dump(mode="json")
    if isinstance(brief, SceneBoardRoleBriefV2):
        projection = scene_projection or context.scene_environment_projection
        environment_identity = (
            projection.environment_identity if projection else brief.environment_identity
        )
        spatial_logic = projection.spatial_logic if projection else brief.spatial_logic
        lighting = projection.lighting if projection else brief.lighting
        materials = projection.materials if projection else brief.materials
        atmosphere = projection.atmosphere if projection else brief.atmosphere
        if context.node_parameters.get("scene_asset_kind") == "multi_view":
            scene_views = _scene_views(brief)
        elif projection is not None:
            scene_views = projection.views[:1]
        else:
            scene_views = tuple(brief.views[:1])
        panels = tuple(
            SceneBoardPanelV2(
                panel_index=index,
                view_or_zone=(
                    view.view_or_zone if isinstance(view, SceneEnvironmentViewV1) else view
                ),
                spatial_description=(
                    view.spatial_details
                    if isinstance(view, SceneEnvironmentViewV1)
                    else f"{spatial_logic} View: {view}."
                ),
                lighting_material_detail=f"{lighting} {materials}",
            )
            for index, view in enumerate(scene_views or brief.views, start=1)
        )
        return SceneDesignBoardContentV2(
            scene_asset_kind=(
                "multi_view"
                if context.node_parameters.get("scene_asset_kind") == "multi_view"
                else "main"
            ),
            scene_identity=environment_identity,
            environment_summary=f"{spatial_logic} {atmosphere}",
            layout=(
                "Nine distinct viewpoints of the same primary location."
                if context.node_parameters.get("scene_asset_kind") == "multi_view"
                else "One full-frame primary location."
            ),
            lighting=lighting,
            materials=materials,
            time_of_day="Use the accepted scene time of day.",
            style=style,
            panels=panels,
            environment_projection_digest=(
                projection.projection_digest if projection is not None else None
            ),
        ).model_dump(mode="json")
    if isinstance(brief, ScriptRoleBriefV2):
        return {
            "production_handoff": list(brief.production_handoff),
            "content": (
                f"{brief.narrative}\n\nTiming: {brief.timing}\n"
                f"Dialogue: {brief.dialogue}\nVoiceover: {brief.voiceover}"
                + (
                    "\nProduction handoff (planned; separate execution required): "
                    + "; ".join(brief.production_handoff)
                    if brief.production_handoff
                    else ""
                )
            ),
        }
    if isinstance(brief, StoryboardGridRoleBriefV2):
        projection = context.storyboard_projection
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
        if projection is not None:
            panels = tuple(
                StoryboardPanelV2(
                    panel_index=row.panel_index,
                    beat=row.content_beat,
                    composition=row.camera_description,
                    camera=row.camera_description,
                    subject_action=row.content_beat,
                    continuity_from_previous=(
                        projection.sequence.start_state
                        if row.panel_index == 1
                        else projection.rows[row.panel_index - 2].content_beat
                    ),
                )
                for row in projection.rows
            )
        return StoryboardGridContentV2(
            production_handoff=brief.production_handoff,
            sequence_summary=(
                projection.sequence.narrative_goal if projection else brief.sequence_summary
            ),
            narrative_goal=(
                projection.sequence.narrative_goal
                if projection
                else context.selected_direction or brief.sequence_summary
            ),
            style=style,
            panels=panels,
        ).model_dump(mode="json")
    if isinstance(brief, VideoSegmentRoleBriefV2):
        style = VisualStyleContractV2(
            style_prompt=brief.target_style,
            source="video_skill" if context.style_projection else "platform_default",
        )
        return VideoSegmentContentV2(
            production_handoff=brief.production_handoff,
            segment_summary=brief.segment_summary,
            duration_seconds=brief.duration_seconds,
            storyboard_content=brief.action,
            representation_mode=(context.video_representation_mode or "illustrated"),
            style_expression=context.style_expression,
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


def role_prompt_text_violation(
    role_variant: str,
    text: str,
    *,
    field_path: str,
) -> RolePromptViolationV1 | None:
    """Return a safe deterministic violation without exposing matched text."""

    normalized = text.casefold()
    negated_match_ranges: list[tuple[int, int]] = []
    phrases = sorted(
        _ROLE_PROMPT_CONFLICTS.get(role_variant, ()),
        key=len,
        reverse=True,
    )
    for phrase in phrases:
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])")
        for match in pattern.finditer(normalized):
            match_range = (match.start(), match.end())
            if _is_explicitly_negated(normalized, match.start()):
                negated_match_ranges.append(match_range)
                continue
            if any(
                negated_start <= match_range[0] and match_range[1] <= negated_end
                for negated_start, negated_end in negated_match_ranges
            ):
                continue
            return RolePromptViolationV1(
                role_variant=role_variant,
                violation_category=_SCENE_CONFLICT_CATEGORIES.get(
                    phrase,
                    "cross_role_content",
                ),
                field_path=field_path,
            )
    return None


def role_prompt_failure_disposition(*, user_authored: bool) -> ActionableFailureV1:
    """Map a Scene role failure into the shared actionable-failure authority."""

    if user_authored:
        return ActionableFailureV1(
            failure_class="deterministic",
            retry_scope="none",
            user_action="revise",
        )
    return ActionableFailureV1(
        failure_class="external",
        retry_scope="prompt_preparation",
        user_action="retry",
    )


def _validate_role_prompt_text(
    role_variant: str,
    text: str,
    *,
    field_path: str,
    node_id: str,
    workflow_id: str,
) -> None:
    violation = role_prompt_text_violation(role_variant, text, field_path=field_path)
    if violation is not None:
        logger.warning(
            "%s",
            json.dumps(
                {
                    "event": "role_prompt_soft_violation",
                    **violation.model_dump(mode="json"),
                    "call_site": "compiler",
                    "node_id": node_id,
                    "workflow_id": workflow_id,
                },
                sort_keys=True,
            ),
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


def _error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_role_prompt_compiler",
        details=details,
    )
