"""Central versioned provider prompt compilation for Agent Canvas media roles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_ad_media import (
    AdMediaRoleContractV2,
    AdReferenceBundleV2,
    BgmContentV2,
    CharacterDesignAssetContentV2,
    CompiledProviderPromptV2,
    ProviderReferenceInstructionV1,
    DesignAssetContentV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
    VisualStyleContractV2,
    resolve_visual_style,
)
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2
from app.schemas.agent_canvas_prompt_assertion import ProviderPromptAssertionEvidenceV1
from app.schemas.agent_canvas_reference_conditioning import ReferenceConditioningPlanV1
from app.services.agent_canvas_ad_media import AdMediaRoleRegistry
from app.services.agent_canvas_character_reference_prompt_policy import (
    CharacterReferencePromptPolicy,
)
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_execution_mode import has_managed_prompt_preparation
from app.services.agent_canvas_role_prompt_compiler import (
    role_prompt_failure_disposition,
    role_prompt_text_violation,
)
from app.services.agent_canvas_prompt_assertion_policy import (
    PromptAssertionEvidenceValidator,
    PromptAssertionPolicyRegistry,
)
from app.services.agent_canvas_reference_semantics import (
    compile_provider_reference_instruction,
)


@dataclass(frozen=True, slots=True)
class AgentCanvasPromptRegistration:
    semantic_role: str
    registry_ref: str
    boundary: str
    negative_boundary: str
    registry_digest: str


_ROLE_BOUNDARIES = {
    "product": (
        "Render one product identity with exact geometry, materials, marks, and proportions.",
        "Do not add people or a narrative environment unless explicitly declared.",
    ),
    "prop": (
        "Render one isolated prop identity and material design.",
        "Do not add unrelated products, people, or narrative action.",
    ),
    "character": (
        "Render one character identity, wardrobe, silhouette, and neutral presentation.",
        "Do not add product placement or a narrative scene unless explicitly declared.",
    ),
    "scene": (
        "Render one consistent environment as a complete 3x3 spatial design board.",
        "Do not progress narrative action across panels.",
    ),
    "storyboard_sequence": (
        "Render one complete 3x3 storyboard image for one coherent sequence. "
        "Keep all nine distinct frames in strict reading order with consistent "
        "identities, world details, visual style, and narrative continuity. "
        "Do not render labels or panel numbers anywhere in the image. Use visual "
        "storytelling without visible text in every frame.",
        "Do not generate captions, panel numbers, subtitles, speech bubbles, logos, or watermarks.",
    ),
    "storyboard_video": (
        "Render one video segment from the complete bound storyboard grid.",
        "Do not generate background music; preserve declared dialogue, ambience, and effects.",
    ),
    "bgm": (
        "Render one instrumental background music track.",
        "No vocals, lyrics, speech, or spoken words.",
    ),
    "general_image": (
        "Render one image from the saved Node prompt.",
        "Do not add undeclared identities or text.",
    ),
    "general_video": (
        "Render one video from the saved Node prompt and explicit Bindings.",
        "Do not add background music unless the prompt explicitly requests it.",
    ),
    "general_audio": (
        "Render one audio asset from the saved Node prompt.",
        "Do not add undeclared speech or lyrics.",
    ),
}
_STYLE_ROLE_BY_SEMANTIC_ROLE = {
    "product": "product",
    "prop": "prop",
    "character": "character",
    "scene": "scene",
    "storyboard_sequence": "storyboard",
    "storyboard_video": "video",
    "bgm": "bgm",
    "general_image": "quick_media",
    "general_video": "quick_media",
    "general_audio": "quick_media",
}
_WORLD_SETTING_ROLE_LABEL = {
    "product": "Product",
    "prop": "Prop",
    "character": "Character",
    "scene": "Scene",
    "storyboard": "Storyboard",
    "video": "Video",
    "bgm": "BGM",
}


def list_agent_canvas_prompt_registrations() -> tuple[AgentCanvasPromptRegistration, ...]:
    return tuple(
        _registration(role, boundary, negative)
        for role, (boundary, negative) in _ROLE_BOUNDARIES.items()
    )


class AgentCanvasProviderPromptCompiler:
    """Compile deterministic role prompts without an LLM or sibling context."""

    def __init__(self, roles: AdMediaRoleRegistry | None = None) -> None:
        self._roles = roles or AdMediaRoleRegistry()
        self._registrations = {
            item.semantic_role: item for item in list_agent_canvas_prompt_registrations()
        }

    def compile(
        self,
        node: CanvasNodeV2,
        role_contract: AdMediaRoleContractV2,
        reference_bundle: AdReferenceBundleV2,
        *,
        creative_direction_projection: Mapping[str, object] | None = None,
        world_setting: WorldSettingContextEnvelopeV2 | None = None,
    ) -> CompiledProviderPromptV2:
        reference_only = (
            node.semantic_role in {"general_image", "general_video", "general_audio"}
            and not has_managed_prompt_preparation(node)
            and bool(reference_bundle.references)
        )
        if not str(node.generation_prompt or "").strip() and not reference_only:
            raise _error(
                "node_prompt_empty",
                "A media Node requires a saved generation prompt before provider preparation.",
            )
        _validate_editable_prompt_authority(node)
        if node.semantic_role == "scene":
            violation = role_prompt_text_violation(
                "scene_board",
                str(node.generation_prompt),
                field_path="generation_prompt",
            )
            if violation is not None:
                disposition = role_prompt_failure_disposition(
                    user_authored=not has_managed_prompt_preparation(node)
                )
                raise V2PersistenceError(
                    "node_prompt_role_contract_invalid",
                    "The Scene prompt conflicts with its environment-only role contract.",
                    stage="agent_canvas_provider_prompt_compiler",
                    details={
                        "role_variant": violation.role_variant,
                        "violation_category": violation.violation_category,
                        "field_path": violation.field_path,
                        "actionable_failure": disposition.model_dump(mode="json"),
                        "retryable": disposition.retryable,
                    },
                )
        if role_contract.semantic_role != node.semantic_role:
            raise _error(
                "provider_prompt_contract_failed",
                "Node role does not match the prompt contract.",
            )
        registration = self._registrations.get(node.semantic_role)
        if registration is None:
            raise _error(
                "provider_prompt_contract_failed",
                "Provider prompt registration is missing.",
            )
        assertion_evidence = None
        preparation = node.prompt_preparation
        if preparation.role_variant is not None or preparation.recipe_id is not None:
            if preparation.recipe_id is None or preparation.recipe_version is None:
                raise _error(
                    "node_prompt_assertion_contract_invalid",
                    "Guided prompt recipe identity is incomplete.",
                )
            evidence = preparation.assertion_evidence
            if evidence is None:
                raise _error(
                    "node_prompt_assertion_evidence_missing",
                    "Current prompt assertion evidence is required.",
                )
            native_audio_required = (
                any(
                    item.name == "generate_audio" and item.value is True
                    for item in preparation.parameter_origins
                )
                or node.parameters.get("generate_audio") is True
            )
            policy = PromptAssertionPolicyRegistry().resolve_for_video_audio(
                preparation.recipe_id,
                preparation.recipe_version,
                native_audio_required=native_audio_required,
            )
            PromptAssertionEvidenceValidator().validate_preparation(
                policy=policy,
                prompt_digest=hashlib.sha256(
                    str(node.generation_prompt).encode("utf-8")
                ).hexdigest(),
                evidence=evidence,
                current_sources=evidence.source_snapshots,
                current_document_revisions=evidence.document_revisions,
                current_sequence_id=evidence.sequence_id,
            )
            if str(node.generation_prompt).count(policy.assertion_block) != 1:
                raise _error(
                    "node_prompt_assertion_contract_invalid",
                    "Canonical prompt assertion block is missing or duplicated.",
                )
            if (
                node.metadata.get("prompt_assertion_policy_ref") != policy.policy_ref
                or node.metadata.get("prompt_assertion_policy_digest") != policy.policy_digest
                or node.metadata.get("prompt_assertion_evidence_digest") != evidence.evidence_digest
                or not _reference_evidence_matches(evidence.source_snapshots, reference_bundle)
            ):
                raise _error(
                    "node_prompt_assertion_contract_invalid",
                    "Prompt assertion evidence does not match provider input authority.",
                )
            if preparation.role_variant == "character_turnaround":
                projection_digest = preparation.character_identity_projection_digest
                if (
                    projection_digest is None
                    or evidence.character_identity_projection_digest != projection_digest
                    or node.structured_content.get("identity_projection_digest")
                    != projection_digest
                ):
                    raise _error(
                        "character_parent_identity_projection_invalid",
                        "Character Turnaround projection evidence is missing or stale.",
                    )
            if preparation.role_variant == "scene_board":
                projection_digest = preparation.scene_environment_projection_digest
                if (
                    projection_digest is None
                    or evidence.scene_environment_projection_digest != projection_digest
                    or node.structured_content.get("environment_projection_digest")
                    != projection_digest
                ):
                    raise _error(
                        "scene_environment_projection_invalid",
                        "Scene environment projection evidence is missing or stale.",
                    )
        if creative_direction_projection is not None:
            CreativeDirectionService().validate_role_projection(
                _STYLE_ROLE_BY_SEMANTIC_ROLE[node.semantic_role],
                creative_direction_projection,
            )
        if world_setting is not None:
            expected_audience = _STYLE_ROLE_BY_SEMANTIC_ROLE[node.semantic_role]
            if world_setting.target_audience != expected_audience:
                raise _error(
                    "world_setting_context_audience_invalid",
                    "World Setting context audience does not match the target role.",
                )
        try:
            structured_payload = {
                key: value
                for key, value in node.structured_content.items()
                if key not in {"reference_style_policy", "reference_conditioning_plan"}
            }
            structured = self._roles.validate_structured_content(
                node.semantic_role,
                structured_payload,
            )
        except V2PersistenceError as error:
            if node.semantic_role in {"storyboard_video", "general_video"} and (
                "style" in node.structured_content
            ):
                raise _error(
                    "provider_prompt_style_contract_invalid",
                    "Video style contract is invalid before provider dispatch.",
                ) from error
            raise
        style = _style_from_content(
            node,
            structured,
            creative_direction_projection=creative_direction_projection,
        )
        character_policy = (
            CharacterReferencePromptPolicy().compile(structured)
            if isinstance(structured, CharacterDesignAssetContentV2)
            else None
        )
        body = _render_content(structured)
        reference_identities = _render_reference_identities(
            reference_bundle,
            target_semantic_role=node.semantic_role,
        )
        references = "\n".join(
            (
                f"- Image {index}: binding={item.binding_id}; asset={item.asset_id}; "
                f"media={item.media_type}; semantic_reference_role="
                f"{item.semantic_reference_role or 'unspecified'}; "
                f"url={item.access_descriptor.media_url}"
            )
            for index, item in enumerate(reference_bundle.references, start=1)
        )
        try:
            conditioning_plan = _conditioning_plan_from_node(node)
            if conditioning_plan is not None:
                _validate_conditioning_plan(conditioning_plan, node, reference_bundle)
                reference_instructions = (_conditioning_instruction(conditioning_plan),)
            else:
                reference_instructions = tuple(
                    instruction
                    for item in reference_bundle.references
                    if (
                        instruction := item.reference_instruction
                        or compile_provider_reference_instruction(
                            reference_kind=item.reference_kind,
                            reference_purpose=item.reference_purpose,
                        )
                    )
                )
        except ValueError as error:
            raise _error(
                "provider_reference_instruction_invalid",
                "Guided reference semantics are invalid for provider delivery.",
            ) from error
        storyboard_anchor_clause = _storyboard_visual_anchor_clause(reference_bundle)
        is_video = node.semantic_role in {"storyboard_video", "general_video"}
        style_clause = (
            f"Authoritative target output style ({style.source}):\n{style.style_prompt}"
            if is_video
            else f"Visual style ({style.source}):\n{style.style_prompt}"
        )
        prompt_parts = (
            character_policy.positive_boundary if character_policy is not None else "",
            registration.boundary,
            f"Creative prompt:\n{node.generation_prompt or node.summary_prompt or ''}",
            f"Structured role content:\n{body}",
            reference_identities,
            storyboard_anchor_clause,
            (
                _render_world_setting(world_setting)
                if world_setting is not None and node.semantic_role != "character"
                else ""
            ),
            f"Explicit references:\n{references}" if references else "",
        )
        prompt = "\n\n".join(
            part
            for part in (
                (*prompt_parts, style_clause)
                if is_video
                else (*prompt_parts[:5], style_clause, *prompt_parts[5:])
            )
            if part
        )
        negative = "\n".join(
            (
                character_policy.negative_boundary if character_policy is not None else "",
                registration.negative_boundary,
                *style.negative_style_constraints,
            )
        )
        registry_digest = (
            _digest(
                {
                    "role_registry_digest": registration.registry_digest,
                    "character_policy_digest": character_policy.policy_digest,
                }
            )
            if character_policy is not None
            else registration.registry_digest
        )
        context = {
            "node_id": node.node_id,
            "node_revision": node.revision,
            "prompt_context_snapshot_id": node.prompt_context_snapshot_id,
            "role_contract_version": node.role_contract_version,
            "structured_content": node.structured_content,
            "world_setting_context": (
                {
                    "source_node_id": world_setting.source_node_id,
                    "source_node_revision": world_setting.source_node_revision,
                    "compiler_digest": world_setting.compiler_digest,
                    "context_digest": world_setting.context_digest,
                }
                if world_setting is not None
                else None
            ),
        }
        final_prompt_digest = hashlib.sha256(prompt.encode()).hexdigest()
        if preparation.assertion_evidence is not None:
            evidence = preparation.assertion_evidence
            assertion_evidence = ProviderPromptAssertionEvidenceV1(
                policy_ref=evidence.policy_ref,
                policy_version=evidence.policy_version,
                policy_digest=evidence.policy_digest,
                recipe_id=evidence.recipe_id,
                recipe_version=evidence.recipe_version,
                assertion_ids=evidence.assertion_ids,
                preparation_evidence_digest=evidence.evidence_digest,
                assertion_block_digest=evidence.assertion_block_digest,
                prepared_prompt_digest=evidence.prepared_prompt_digest,
                provider_prompt_digest=final_prompt_digest,
            )
        return CompiledProviderPromptV2(
            semantic_role=node.semantic_role,
            prompt_registry_ref=registration.registry_ref,
            prompt_registry_digest=registry_digest,
            render_context_digest=_digest(context),
            prompt_digest=final_prompt_digest,
            reference_bundle_digest=reference_bundle.bundle_digest,
            style_source=style.source,
            prompt=prompt,
            negative_prompt=negative,
            provider_parameters=_provider_parameters(node.semantic_role),
            reference_instructions=reference_instructions,
            assertion_evidence=assertion_evidence,
        )


def _reference_evidence_matches(source_snapshots, reference_bundle: AdReferenceBundleV2) -> bool:
    expected = tuple(item for item in source_snapshots if item.source_kind == "binding")
    expected_by_binding = {item.binding_id: item for item in expected}
    if None in expected_by_binding or len(expected_by_binding) != len(expected):
        return False
    actual_binding_ids: set[str] = set()
    for reference in reference_bundle.references:
        snapshot = expected_by_binding.get(reference.binding_id)
        if snapshot is None or reference.binding_id in actual_binding_ids:
            return False
        actual_binding_ids.add(reference.binding_id)
        if (
            snapshot.binding_revision != reference.binding_revision
            or snapshot.source_node_id != reference.source_node_id
            or snapshot.source_node_revision != reference.source_node_revision
            or snapshot.sequence_id != reference.source_sequence_id
        ):
            return False
        if snapshot.asset_id is not None and (
            snapshot.asset_id != reference.asset_id
            or snapshot.asset_version_id != reference.asset_version_id
        ):
            return False
    return all(
        snapshot.binding_id in actual_binding_ids
        for snapshot in expected
        if snapshot.asset_id is not None
    )


def _conditioning_plan_from_node(node: CanvasNodeV2) -> ReferenceConditioningPlanV1 | None:
    raw = node.metadata.get("prompt_reference_conditioning_plan")
    if raw is None:
        return None
    try:
        return ReferenceConditioningPlanV1.model_validate(raw)
    except ValidationError as error:
        raise _error(
            "reference_conditioning_plan_invalid",
            "Reference conditioning metadata is invalid before provider delivery.",
        ) from error


def _validate_conditioning_plan(
    plan: ReferenceConditioningPlanV1,
    node: CanvasNodeV2,
    reference_bundle: AdReferenceBundleV2,
) -> None:
    expected_role = {"character": "character_main", "scene": "scene_board"}.get(node.semantic_role)
    if expected_role != plan.target_role or len(reference_bundle.references) != 1:
        raise _error(
            "reference_conditioning_plan_invalid",
            "Conditioning plan role or reference cardinality is invalid.",
        )
    reference = reference_bundle.references[0]
    if (
        reference.display_order != plan.reference_position - 1
        or reference.binding_id != plan.provenance.binding_id
        or reference.binding_revision != plan.provenance.binding_revision
        or reference.asset_id != plan.provenance.asset_id
        or reference.asset_version_id != plan.provenance.asset_version_id
        or reference.source_node_id != plan.provenance.source_node_id
        or reference.source_node_revision != plan.provenance.source_node_revision
        or reference.reference_kind != plan.reference_kind
        or reference.reference_purpose != plan.reference_purpose
        or reference.semantic_reference_role != plan.semantic_reference_role
    ):
        raise _error(
            "reference_conditioning_plan_stale",
            "Conditioning plan does not match the current delivered reference.",
        )


def _conditioning_instruction(plan: ReferenceConditioningPlanV1):
    role_label = "Character Main" if plan.target_role == "character_main" else "Scene Main"
    protected = ", ".join(plan.protected_dimensions)
    allowed = ", ".join(plan.allowed_change_dimensions)
    override = (
        ", ".join(plan.explicit_override_dimensions)
        if plan.explicit_override_dimensions
        else "none"
    )
    return ProviderReferenceInstructionV1(
        reference_kind=plan.reference_kind,
        semantic_purpose=plan.reference_purpose,
        instruction=(
            f"Image 1 is the primary {role_label} reference. Preserve protected dimensions: "
            f"{protected}. Allowed changes: {allowed}. "
            f"Explicit structured overrides: {override}. Do not substitute an unrelated "
            "subject or environment."
        ),
    )


def _registration(
    role: str,
    boundary: str,
    negative: str,
) -> AgentCanvasPromptRegistration:
    registry_ref = f"adcraft.agent_canvas.{role}.v1"
    return AgentCanvasPromptRegistration(
        semantic_role=role,
        registry_ref=registry_ref,
        boundary=boundary,
        negative_boundary=negative,
        registry_digest=hashlib.sha256(
            f"{registry_ref}\n{boundary}\n{negative}".encode()
        ).hexdigest(),
    )


def _storyboard_visual_anchor_clause(reference_bundle: AdReferenceBundleV2) -> str:
    anchors = tuple(
        (index, item)
        for index, item in enumerate(reference_bundle.references, start=1)
        if item.storyboard_reference_purpose == "sequence_visual_anchor"
    )
    if not anchors:
        return ""
    if len(anchors) != 1:
        raise _error(
            "storyboard_visual_anchor_invalid",
            "A later storyboard grid requires exactly one sequence visual anchor.",
        )
    index, _ = anchors[0]
    return (
        f"Image {index} is the authoritative sequence visual anchor. Preserve its "
        "character identity, product identity, environment, palette, composition "
        "language, and rendering style while following only this Node's own nine-panel "
        "storyboard prompt."
    )


_STYLE_PROJECTION_FIELDS = (
    "style_prompt",
    "role_guidance",
    "global_guidance",
    "rendering_style",
    "summary",
)


def _style_from_content(
    node: CanvasNodeV2,
    structured: object,
    *,
    creative_direction_projection: Mapping[str, object] | None = None,
) -> VisualStyleContractV2:
    style = getattr(structured, "style", None)
    if isinstance(style, VisualStyleContractV2):
        return style
    if node.semantic_role in {"storyboard_video", "general_video"}:
        if creative_direction_projection is not None:
            return _style_from_projection(creative_direction_projection)
        return resolve_visual_style()
    return resolve_visual_style()


def _style_from_projection(
    projection: Mapping[str, object],
) -> VisualStyleContractV2:
    for field in _STYLE_PROJECTION_FIELDS:
        if field not in projection:
            continue
        value = projection[field]
        if not isinstance(value, str) or not value.strip():
            raise _error(
                "provider_prompt_style_contract_invalid",
                "Video style projection must contain one bounded non-empty string.",
            )
        normalized = value.strip()
        if normalized.startswith(("{", "[")):
            raise _error(
                "provider_prompt_style_contract_invalid",
                "Video style projection must not be a stringified mapping.",
            )
        try:
            return VisualStyleContractV2(
                style_prompt=normalized,
                source="user" if field == "style_prompt" else "video_skill",
            )
        except ValidationError as error:
            raise _error(
                "provider_prompt_style_contract_invalid",
                "Video style projection exceeds the bounded style contract.",
            ) from error
    return resolve_visual_style()


def _render_content(structured: object) -> str:
    if isinstance(structured, SceneDesignBoardContentV2):
        return "\n".join(
            [
                f"Environment: {structured.scene_identity}",
                f"Layout: {structured.layout}",
                *[
                    (
                        f"Panel {panel.panel_index}: {panel.view_or_zone}; "
                        f"{panel.spatial_description}; {panel.lighting_material_detail}"
                    )
                    for panel in structured.panels
                ],
            ]
        )
    if isinstance(structured, StoryboardGridContentV2):
        frame_positions = (
            "Top-left frame",
            "Top-center frame",
            "Top-right frame",
            "Middle-left frame",
            "Center frame",
            "Middle-right frame",
            "Bottom-left frame",
            "Bottom-center frame",
            "Bottom-right frame",
        )
        return "\n".join(
            [
                f"Sequence: {structured.sequence_summary}",
                *[
                    (
                        f"{frame_positions[panel.panel_index - 1]} content: "
                        f"{panel.beat}; {panel.composition}; "
                        f"{panel.camera}; {panel.subject_action}; "
                        f"continuity={panel.continuity_from_previous}"
                    )
                    for panel in structured.panels
                ],
            ]
        )
    if isinstance(structured, VideoSegmentContentV2):
        return "\n".join(
            (
                f"Segment: {structured.segment_summary}",
                f"Duration: {structured.duration_seconds} seconds",
                f"Storyboard: {structured.storyboard_content}",
                f"Dialogue: {structured.dialogue}",
                f"Voice style: {structured.voice_style}",
                f"Environment sound: {structured.environment_sound}",
                f"Action effects: {structured.action_effects}",
            )
        )
    if isinstance(structured, BgmContentV2):
        return "\n".join(
            (
                f"Music: {structured.music_summary}",
                f"Duration: {structured.duration_seconds} seconds",
                f"Pace: {structured.pace}",
                f"Energy: {structured.energy_curve}",
                f"Instrumentation: {structured.instrumentation}",
                f"Mood: {structured.mood}",
            )
        )
    if isinstance(structured, DesignAssetContentV2):
        return f"Identity: {structured.subject_identity}\nDesign: {structured.design_summary}"
    if structured is None:
        return ""
    return json.dumps(structured.model_dump(mode="json"), sort_keys=True)


def _provider_parameters(semantic_role: str) -> dict[str, str | int | float | bool]:
    if semantic_role == "storyboard_sequence":
        return {"sequential_generation": False}
    return {}


def _render_world_setting(context: WorldSettingContextEnvelopeV2) -> str:
    parts = [
        "Authoritative World setting context "
        "(overrides conflicting model-authored details):\n"
        f"{context.shared_summary}"
    ]
    if context.relevant_world_rules:
        parts.append(
            "World rules:\n" + "\n".join(f"- {item}" for item in context.relevant_world_rules)
        )
    if context.relevant_visual_continuity:
        parts.append(
            "Visual continuity:\n"
            + "\n".join(f"- {item}" for item in context.relevant_visual_continuity)
        )
    return "\n\n".join(parts)


def _render_reference_identities(
    reference_bundle: AdReferenceBundleV2,
    *,
    target_semantic_role: str,
) -> str:
    identities = [
        {
            "binding_id": reference.binding_id,
            "source_role": reference.source_semantic_role,
            "semantic_reference_role": reference.semantic_reference_role,
            "occurrence_id": reference.occurrence_id,
            "character_phase": reference.character_phase,
            "facts": reference.source_identity_facts,
        }
        for reference in reference_bundle.references
        if reference.source_identity_facts
    ]
    if not identities and not reference_bundle.references:
        return ""
    turnaround_clause = (
        "A Character Turnaround reference is one person shown across front, side, and back "
        "views. Preserve identity cues but render the target in its own requested medium.\n"
        if any(
            reference.source_identity_facts.get("character_asset_kind") == "turnaround"
            for reference in reference_bundle.references
        )
        else ""
    )
    video_semantics = ""
    if target_semantic_role in {"storyboard_video", "general_video"}:
        roles = {reference.semantic_reference_role for reference in reference_bundle.references}
        instructions = []
        if "subject_reference" in roles:
            instructions.append(
                "Subject references control identity, wardrobe, silhouette, and proportions."
            )
        if "environment_reference" in roles:
            instructions.append(
                "Scene references control spatial identity, layout, lighting, and materials."
            )
        if "storyboard_visual_reference" in roles:
            instructions.append(
                "Storyboard references control frame order, composition, action, and continuity."
            )
        if roles.intersection({"style_reference", "style_composition_reference"}):
            instructions.append(
                "Explicit style references are style-bearing inputs, subject to the final "
                "target output style."
            )
        instructions.append(
            "Non-style references do not transfer photographic, live-action, illustration, "
            "line-art, cel-shaded, animated, or 3D rendering medium to the target Video."
        )
        video_semantics = "Video reference-use semantics:\n" + "\n".join(instructions) + "\n"
    return (
        video_semantics + "Authoritative bound reference identities:\n"
        "These persisted Binding facts override conflicting model-authored details. "
        "Keep their identities and environments unchanged while retaining creative "
        "freedom for panel action, composition, and camera.\n"
        + turnaround_clause
        + "\n".join(
            f"- {json.dumps(identity, sort_keys=True, ensure_ascii=True)}"
            for identity in identities
        )
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _validate_editable_prompt_authority(node: CanvasNodeV2) -> None:
    projection = node.prompt_presentation
    if projection is None:
        return
    prompt = str(node.generation_prompt or "")
    expected_digest = f"sha256:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}"
    review_revision = node.metadata.get("guided_review_node_revision")
    revision_matches = projection.revision == node.revision or (
        isinstance(review_revision, int)
        and not isinstance(review_revision, bool)
        and review_revision == node.revision
        and projection.revision + 1 == node.revision
    )
    if (
        projection.text != prompt
        or not revision_matches
        or projection.prompt_digest != expected_digest
    ):
        raise _error(
            "prompt_revision_conflict",
            "The editable prompt projection does not match the frozen Node revision.",
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_provider_prompt_compiler")
