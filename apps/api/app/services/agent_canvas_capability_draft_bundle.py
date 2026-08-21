"""Pure capability Draft bundle construction for Proposal materialization."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from app.schemas.agent_canvas import (
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_capability_drafts import CapabilityDraftBundleV1
from app.schemas.agent_canvas_creative_session import (
    CharacterImageSpecialistDraftV2,
    DraftReferenceIntentV2,
    SpecialistDraftV2,
)
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    CharacterMaterializationResultV1,
    ParentDerivedMaterializationIntentV1,
    ParentNodeSnapshotV1,
    MaterializationNormalizationV1,
    ProductMaterializationResultV1,
    ProposalApplicationEnvelopeV1,
    QuickMediaMaterializationResultV1,
    WorldSettingMaterializationResultV1,
)
from app.schemas.agent_canvas_materialization_commit import (
    NodePromptPreparationIntentV1,
)
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV2,
    WorldSettingDocumentV2,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_reference_semantics import AgentCanvasReferenceSemanticPolicy
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)


_MAIN_PROMPT = """Create one detailed semi-realistic 2D commercial character illustration, clearly illustrated rather than photographed. Show exactly one full-body human in a natural standing pose with a slight three-quarter front view on a seamless light-neutral design background with no environmental objects. Use only a subtle grounding shadow. Preserve readable facial features, hair, wardrobe construction, body proportions, silhouette, and color palette."""

_TURNAROUND_PROMPT = """Use the bound Character Main image as the sole identity master. Render one turnaround sheet with exactly three unlabeled full-body figures arranged left-to-right as forward-facing, exact side profile, and rear-facing on a seamless light-neutral design background. All three views are the same person with identical face, hair, wardrobe, proportions, silhouette, materials, palette, and detailed semi-realistic illustration treatment. Keep the sheet blank: no headings, orientation labels, captions, typography, logos, or watermarks anywhere. Do not reinterpret or redesign the identity."""

_PROVENANCE_KEYS = {
    "materialization_mode",
    "warning_code",
    "operation_policy_id",
    "normalization_mode",
    "normalization_warnings",
    "character_pair_id",
    "product_pair_id",
    "character_asset_kind",
    "source_agent_document_id",
    "source_sequence_id",
}


class CapabilityDraftBundleBuilder:
    """Build every Node, Binding, and prompt intent without side effects."""

    def build(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        materialization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1,
    ) -> CapabilityDraftBundleV1:
        if isinstance(materialization, CapabilityMaterializationContextV1):
            return self._build_progressive(envelope, materialization)
        return self._build_normalized(envelope, materialization)

    def _build_progressive(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
    ) -> CapabilityDraftBundleV1:
        definitions = stage_definitions(envelope.capability_id, envelope.operation_kind)
        node_ids = tuple(
            f"node_{_digest(f'{envelope.materialization_id}:{_pair_node_suffix(envelope, draft_key)}')[:32]}"
            for draft_key, *_ in definitions
        )
        references = (
            ()
            if envelope.operation_kind == "derivative"
            and envelope.capability_id in {"product_design", "character_design"}
            else _reference_intents(envelope)
        )
        pair_id = (
            f"pair_{_digest(envelope.parent_snapshot.node_id)[:32]}"
            if envelope.operation_kind == "derivative" and envelope.parent_snapshot is not None
            else f"pair_{_digest(node_ids[0])[:32]}"
            if envelope.capability_id in {"product_design", "character_design"}
            else None
        )
        character_pair_id = pair_id if envelope.capability_id == "character_design" else None
        drafts: list[SpecialistDraftV2] = []
        for draft_key, node_type, role, title_suffix, identity in definitions:
            if (
                envelope.capability_id == "video_direction"
                and role == "storyboard_video"
                and not _has_storyboard_visual_reference(envelope)
            ):
                role = "general_video"
            parameters = _stage_parameters(envelope.capability_id, draft_key, context)
            if character_pair_id is not None:
                parameters["character_pair_id"] = character_pair_id
            elif pair_id is not None:
                parameters["product_pair_id"] = pair_id
            drafts.append(
                SpecialistDraftV2(
                    title=_bounded_title(envelope.selected_option.title, title_suffix),
                    node_type=node_type,
                    creative_role=role,
                    summary_prompt=envelope.selected_option.public_summary,
                    generation_prompt=None,
                    structured_content=identity,
                    parameters={
                        **parameters,
                        "stage_draft_key": draft_key,
                        "source_proposal_id": envelope.proposal_id,
                        "source_option_id": envelope.selected_option.option_id,
                    },
                    prompt_context_snapshot_id=envelope.context_snapshot_id,
                    reference_intents=references,
                )
            )
        nodes, external, preparations = _draft_nodes(envelope, tuple(drafts), node_ids)
        internal = _pair_binding(
            envelope,
            nodes=nodes,
            character_pair_id=character_pair_id,
        )
        derivative_intent = _derivative_intent(
            envelope,
            nodes=nodes,
            capability_id=envelope.capability_id,
            pair_id=pair_id,
        )
        bindings = (*external, *internal)
        if envelope.operation_kind == "derivative":
            AgentCanvasRoleReferencePolicyService().require_derivative_bindings(
                envelope.parent_snapshot,
                nodes,
                bindings,
            )
        return CapabilityDraftBundleV1(
            nodes=nodes,
            bindings=bindings,
            prompt_preparations=preparations,
            derivative_intent=derivative_intent,
        )

    def _build_normalized(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1,
    ) -> CapabilityDraftBundleV1:
        if envelope.capability_id == "script_authoring":
            return CapabilityDraftBundleV1(
                nodes=(),
                bindings=(),
                prompt_preparations=(),
            )
        result = normalization.result
        if envelope.capability_id == "world_setting":
            return CapabilityDraftBundleV1(
                nodes=(_world_setting_node(envelope, result),),
                bindings=(),
                prompt_preparations=(),
            )
        if envelope.capability_id == "product_design":
            return _normalized_product_bundle(envelope, normalization)
        if envelope.capability_id == "character_design":
            return _normalized_character_bundle(envelope, normalization)
        if envelope.capability_id == "quick_media":
            quick = QuickMediaMaterializationResultV1.model_validate(result)
            node_type = quick.structured_content.media_type
            creative_role = {
                "image": "general_image",
                "video": "general_video",
                "audio": "general_audio",
            }[node_type]
        elif envelope.capability_id == "video_direction":
            node_type = "video"
            creative_role = (
                "storyboard_video"
                if _has_storyboard_visual_reference(envelope)
                else "general_video"
            )
        else:
            definition = CapabilityPolicyService().definition(envelope.capability_id)
            if definition.node_type is None or definition.creative_role is None:
                raise ValueError("capability_policy_invalid")
            node_type = definition.node_type
            creative_role = definition.creative_role
        draft = SpecialistDraftV2(
            title=str(getattr(result, "title")),
            node_type=node_type,
            creative_role=creative_role,
            summary_prompt=str(getattr(result, "summary_prompt")),
            generation_prompt=getattr(result, "generation_prompt", None),
            structured_content=_model_payload(getattr(result, "structured_content")),
            parameters={
                **normalization.parameters,
                "normalization_mode": normalization.mode,
                "normalization_warnings": list(normalization.warnings),
            },
            parameter_provenance=normalization.parameter_provenance,
            prompt_context_snapshot_id=envelope.context_snapshot_id,
            reference_intents=_reference_intents(envelope),
        )
        nodes, bindings, preparations = _draft_nodes(
            envelope,
            (draft,),
            (f"node_{_digest(envelope.materialization_id)[:32]}",),
        )
        return CapabilityDraftBundleV1(
            nodes=nodes,
            bindings=bindings,
            prompt_preparations=preparations,
        )


def stage_definitions(
    capability_id: str,
    operation_kind: str = "standalone",
) -> tuple[tuple[str, str, str, str, dict], ...]:
    if capability_id in {"product_design", "character_design"} and operation_kind not in {
        "parent",
        "derivative",
    }:
        raise ValueError("parent_derived_operation_required")
    if (
        capability_id not in {"product_design", "character_design"}
        and operation_kind != "standalone"
    ):
        raise ValueError("operation_kind_not_supported")
    if capability_id == "script_authoring":
        return ()
    definitions = {
        "world_setting": (("world-setting", "text", "world_setting", "World Setting", {}),),
        "product_design": {
            "parent": (("product-main", "image", "product", "Main", {"asset_kind": "main"}),),
            "derivative": (
                (
                    "product-multi-view",
                    "image",
                    "product",
                    "Multi-view",
                    {"asset_kind": "multi_view"},
                ),
            ),
        },
        "prop_design": (("prop", "image", "prop", "Prop", {"asset_kind": "main"}),),
        "character_design": {
            "parent": (
                (
                    "character-main",
                    "image",
                    "character",
                    "Main",
                    {"character_asset_kind": "identity_master"},
                ),
            ),
            "derivative": (
                (
                    "character-three-view",
                    "image",
                    "character",
                    "Three-view",
                    {"character_asset_kind": "turnaround"},
                ),
            ),
        },
        "scene_design": (
            (
                "scene-reference-board",
                "image",
                "scene",
                "Reference Board",
                {"scene_asset_kind": "reference_board"},
            ),
        ),
        "script_authoring": (("script", "script", "script", "Script", {}),),
        "storyboard_design": (
            (
                "storyboard-grid",
                "image",
                "storyboard_sequence",
                "Grid 1",
                {"sequence_id": "sequence-1", "panel_count": 9},
            ),
        ),
        "video_direction": (
            (
                "storyboard-video",
                "video",
                "storyboard_video",
                "Video 1",
                {"sequence_id": "sequence-1"},
            ),
        ),
        "bgm_direction": (("bgm", "audio", "bgm", "BGM", {}),),
    }
    try:
        definition = definitions[capability_id]
        if isinstance(definition, dict):
            return definition[operation_kind]
        return definition
    except KeyError as error:
        raise ValueError("stage_content_mismatch") from error


def stage_draft_parameters(
    capability_id: str,
    draft_key: str,
    context: CapabilityMaterializationContextV1,
) -> dict[str, object]:
    return _stage_parameters(capability_id, draft_key, context)


def stage_draft_title(base: str, suffix: str) -> str:
    return _bounded_title(base, suffix)


def _pair_node_suffix(
    envelope: ProposalApplicationEnvelopeV1,
    draft_key: str,
) -> str:
    if envelope.capability_id == "product_design":
        return "main" if envelope.operation_kind == "parent" else "multi-view"
    if envelope.capability_id == "character_design":
        return "main" if envelope.operation_kind == "parent" else "turnaround"
    return draft_key


def character_turnaround_prompt(
    *,
    subject_identity: str,
    design_summary: str,
) -> str:
    """Compile the canonical companion prompt for a Character Main variation."""

    return f"{_TURNAROUND_PROMPT}\n\nIdentity: {subject_identity}. Design: {design_summary}."


def _normalized_character_bundle(
    envelope: ProposalApplicationEnvelopeV1,
    normalization: MaterializationNormalizationV1,
) -> CapabilityDraftBundleV1:
    result = CharacterMaterializationResultV1.model_validate(normalization.result)
    main_node_id = f"node_{_digest(f'{envelope.materialization_id}:main')[:32]}"
    turnaround_node_id = f"node_{_digest(f'{envelope.materialization_id}:turnaround')[:32]}"
    pair_id = (
        f"pair_{_digest(envelope.parent_snapshot.node_id)[:32]}"
        if envelope.operation_kind == "derivative" and envelope.parent_snapshot is not None
        else f"pair_{_digest(main_node_id)[:32]}"
    )
    common_parameters = {
        **normalization.parameters,
        "normalization_mode": normalization.mode,
        "normalization_warnings": list(normalization.warnings),
        "character_pair_id": pair_id,
    }
    main_content = result.structured_content.model_copy(
        update={"character_asset_kind": "identity_master"}
    )
    turnaround_content = result.structured_content.model_copy(
        update={"character_asset_kind": "turnaround"}
    )
    main = CharacterImageSpecialistDraftV2(
        node_type="image",
        creative_role="character",
        title=result.title,
        summary_prompt=result.summary_prompt,
        generation_prompt=f"{_MAIN_PROMPT}\n\nIdentity direction: {result.generation_prompt}",
        structured_content=_model_payload(main_content),
        parameters={**common_parameters, "character_asset_kind": "identity_master"},
        parameter_provenance=normalization.parameter_provenance,
        prompt_context_snapshot_id=envelope.context_snapshot_id,
        reference_intents=_reference_intents(envelope),
    )
    turnaround = CharacterImageSpecialistDraftV2(
        node_type="image",
        creative_role="character",
        title=_suffixed_title(result.title, "Turnaround"),
        summary_prompt=f"Three-view unlabeled identity sheet for {result.title}.",
        generation_prompt=(
            f"{_TURNAROUND_PROMPT}\n\nIdentity: {main_content.subject_identity}. "
            f"Design: {main_content.design_summary}."
        ),
        structured_content=turnaround_content,
        parameters={**common_parameters, "character_asset_kind": "turnaround"},
        parameter_provenance=normalization.parameter_provenance,
        prompt_context_snapshot_id=envelope.context_snapshot_id,
    )
    if envelope.operation_kind == "parent":
        nodes, external, preparations = _draft_nodes(
            envelope,
            (main,),
            (main_node_id,),
        )
        return CapabilityDraftBundleV1(
            nodes=nodes,
            bindings=external,
            prompt_preparations=preparations,
            derivative_intent=_derivative_intent(
                envelope,
                nodes=nodes,
                capability_id="character_design",
                pair_id=pair_id,
            ),
        )
    if envelope.operation_kind == "derivative":
        nodes, external, preparations = _draft_nodes(
            envelope,
            (turnaround,),
            (turnaround_node_id,),
        )
        internal = _pair_binding(envelope, nodes=nodes, character_pair_id=pair_id)
        bindings = (*external, *internal)
        AgentCanvasRoleReferencePolicyService().require_derivative_bindings(
            envelope.parent_snapshot,
            nodes,
            bindings,
        )
        return CapabilityDraftBundleV1(
            nodes=nodes,
            bindings=bindings,
            prompt_preparations=preparations,
        )
    raise ValueError("parent_derived_operation_required")


def _normalized_product_bundle(
    envelope: ProposalApplicationEnvelopeV1,
    normalization: MaterializationNormalizationV1,
) -> CapabilityDraftBundleV1:
    result = ProductMaterializationResultV1.model_validate(normalization.result)
    main_node_id = f"node_{_digest(f'{envelope.materialization_id}:main')[:32]}"
    derivative_node_id = f"node_{_digest(f'{envelope.materialization_id}:multi-view')[:32]}"
    pair_id = (
        f"pair_{_digest(envelope.parent_snapshot.node_id)[:32]}"
        if envelope.operation_kind == "derivative" and envelope.parent_snapshot is not None
        else f"pair_{_digest(main_node_id)[:32]}"
    )
    common_parameters = {
        **normalization.parameters,
        "normalization_mode": normalization.mode,
        "normalization_warnings": list(normalization.warnings),
        "product_pair_id": pair_id,
    }
    main_content = result.structured_content.model_copy(update={"asset_kind": "main"})
    derivative_content = result.structured_content.model_copy(update={"asset_kind": "multi_view"})
    main = SpecialistDraftV2(
        node_type="image",
        creative_role="product",
        title=result.title,
        summary_prompt=result.summary_prompt,
        generation_prompt=result.generation_prompt,
        structured_content=_model_payload(main_content),
        parameters={**common_parameters, "asset_kind": "main"},
        parameter_provenance=normalization.parameter_provenance,
        prompt_context_snapshot_id=envelope.context_snapshot_id,
        reference_intents=_reference_intents(envelope),
    )
    derivative = SpecialistDraftV2(
        node_type="image",
        creative_role="product",
        title=_suffixed_title(result.title, "Multi-view"),
        summary_prompt=f"Multi-view identity sheet for {result.title}.",
        generation_prompt=(
            "Use the bound Product Main image as the sole identity master. "
            "Render front, side, rear, and useful detail views of the same object "
            "with no people, application scene, labels, or unrelated props.\n\n"
            f"Identity: {main_content.subject_identity}. Design: {main_content.design_summary}."
        ),
        structured_content=_model_payload(derivative_content),
        parameters={**common_parameters, "asset_kind": "multi_view"},
        parameter_provenance=normalization.parameter_provenance,
        prompt_context_snapshot_id=envelope.context_snapshot_id,
    )
    if envelope.operation_kind == "parent":
        nodes, external, preparations = _draft_nodes(envelope, (main,), (main_node_id,))
        return CapabilityDraftBundleV1(
            nodes=nodes,
            bindings=external,
            prompt_preparations=preparations,
            derivative_intent=_derivative_intent(
                envelope,
                nodes=nodes,
                capability_id="product_design",
                pair_id=pair_id,
            ),
        )
    if envelope.operation_kind == "derivative":
        nodes, external, preparations = _draft_nodes(
            envelope,
            (derivative,),
            (derivative_node_id,),
        )
        internal = _pair_binding(envelope, nodes=nodes, character_pair_id=pair_id)
        bindings = (*external, *internal)
        AgentCanvasRoleReferencePolicyService().require_derivative_bindings(
            envelope.parent_snapshot,
            nodes,
            bindings,
        )
        return CapabilityDraftBundleV1(
            nodes=nodes,
            bindings=bindings,
            prompt_preparations=preparations,
        )
    raise ValueError("parent_derived_operation_required")


def _draft_nodes(
    envelope: ProposalApplicationEnvelopeV1,
    drafts: tuple[Any, ...],
    node_ids: tuple[str, ...],
) -> tuple[
    tuple[CanvasNodeV2, ...],
    tuple[CanvasBindingV2, ...],
    tuple[NodePromptPreparationIntentV1, ...],
]:
    nodes: list[CanvasNodeV2] = []
    preparations: list[NodePromptPreparationIntentV1] = []
    for node_id, draft in zip(node_ids, drafts, strict=True):
        operation_id = f"prompt_{_digest(f'{envelope.materialization_id}:{node_id}')[:32]}"
        provenance = {
            key: value for key, value in draft.parameters.items() if key in _PROVENANCE_KEYS
        }
        if envelope.operation_kind == "derivative" and envelope.parent_snapshot is not None:
            provenance["derived_parent_snapshot"] = envelope.parent_snapshot.model_dump(mode="json")
            provenance["role_reference_policy_version"] = (
                AgentCanvasRoleReferencePolicyService.policy_version
            )
        if draft.prompt_context_snapshot_id is not None:
            provenance["materialization_context_snapshot_id"] = draft.prompt_context_snapshot_id
        nodes.append(
            CanvasNodeV2(
                node_id=node_id,
                workflow_id=envelope.workflow_id,
                node_type=draft.node_type,
                creative_role=draft.creative_role,
                title=draft.title,
                status="draft",
                summary_prompt=draft.summary_prompt,
                generation_prompt=None,
                structured_content=_model_payload(draft.structured_content),
                parameters={
                    key: value
                    for key, value in draft.parameters.items()
                    if key not in _PROVENANCE_KEYS
                },
                metadata=provenance,
                parameter_provenance=draft.parameter_provenance,
                prompt_context_snapshot_id=(
                    "snapshot_"
                    + _digest(f"{envelope.materialization_id}:{node_id}:prompt-context")[:32]
                ),
                position=CanvasPositionV2(x=0, y=0),
                revision=1,
                prompt_preparation=NodePromptPreparationV1(
                    status="queued",
                    operation_id=operation_id,
                    attempt_no=0,
                    context_snapshot_id=envelope.context_snapshot_id,
                    updated_at=envelope.created_at,
                ),
                created_at=envelope.created_at,
                updated_at=envelope.created_at,
            )
        )
        preparations.append(
            NodePromptPreparationIntentV1(
                operation_id=operation_id,
                node_id=node_id,
                context_snapshot_id=envelope.context_snapshot_id,
            )
        )
    bindings: list[CanvasBindingV2] = []
    semantics = AgentCanvasReferenceSemanticPolicy()
    for node, draft in zip(nodes, drafts, strict=True):
        for intent in sorted(draft.reference_intents, key=lambda item: item.display_order):
            source = (
                CanvasBindingSourceNodeV2(source_node_id=intent.source_id)
                if intent.source_kind == "node"
                else CanvasBindingSourceImageAssetV2(source_asset_id=intent.source_id)
            )
            metadata = semantics.external_metadata(
                source_role=(
                    "world_setting"
                    if intent.semantic_reference_role == "world_setting_reference"
                    else None
                ),
                target_role=node.creative_role,
                semantic_reference_role=intent.semantic_reference_role,
            )
            binding_index = len(bindings)
            bindings.append(
                CanvasBindingV2(
                    binding_id=(
                        "binding_"
                        + _digest(f"{envelope.materialization_id}:reference:{binding_index}")[:32]
                    ),
                    workflow_id=envelope.workflow_id,
                    source=source,
                    target_node_id=node.node_id,
                    input_role=intent.input_role,
                    required=intent.required,
                    enabled=True,
                    order=intent.display_order,
                    metadata=metadata,
                    created_at=envelope.created_at,
                    updated_at=envelope.created_at,
                )
            )
    return tuple(nodes), tuple(bindings), tuple(preparations)


def _pair_binding(
    envelope: ProposalApplicationEnvelopeV1,
    *,
    nodes: tuple[CanvasNodeV2, ...],
    character_pair_id: str | None,
) -> tuple[CanvasBindingV2, ...]:
    if envelope.capability_id not in {"product_design", "character_design"}:
        return ()
    if envelope.operation_kind != "derivative" or envelope.parent_snapshot is None:
        return ()
    expected_role = (
        "character_main" if envelope.capability_id == "character_design" else "product_main"
    )
    if envelope.parent_snapshot.semantic_role != expected_role:
        raise ValueError("parent_materialization_role_invalid")
    if len(nodes) != 1:
        raise ValueError("derivative_materialization_shape_invalid")
    semantics = AgentCanvasReferenceSemanticPolicy()
    is_character = envelope.capability_id == "character_design"
    metadata = (
        semantics.character_pair_metadata(character_pair_id)
        if is_character and character_pair_id is not None
        else semantics.product_pair_metadata()
    )
    suffix = "main-to-turnaround" if is_character else "main-to-secondary"
    return (
        CanvasBindingV2(
            binding_id=f"binding_{_digest(f'{envelope.materialization_id}:{suffix}')[:32]}",
            workflow_id=envelope.workflow_id,
            source=CanvasBindingSourceNodeV2(source_node_id=envelope.parent_snapshot.node_id),
            target_node_id=nodes[0].node_id,
            input_role="image_reference",
            required=True,
            enabled=True,
            order=0,
            label="Character identity master" if is_character else "Required main reference",
            metadata=metadata,
            created_at=envelope.created_at,
            updated_at=envelope.created_at,
        ),
    )


def _derivative_intent(
    envelope: ProposalApplicationEnvelopeV1,
    *,
    nodes: tuple[CanvasNodeV2, ...],
    capability_id: str,
    pair_id: str | None,
) -> ParentDerivedMaterializationIntentV1 | None:
    if envelope.operation_kind != "parent" or capability_id not in {
        "product_design",
        "character_design",
    }:
        return None
    if not nodes or pair_id is None:
        raise ValueError("parent_materialization_missing")
    node = nodes[0]
    prompt_operation_id = node.prompt_preparation.operation_id
    if prompt_operation_id is None:
        raise ValueError("parent_prompt_preparation_identity_missing")
    is_character = capability_id == "character_design"
    derivative_role = "character_turnaround" if is_character else "product_multiview"
    return ParentDerivedMaterializationIntentV1(
        intent_id="derivative_" + _digest(f"{envelope.materialization_id}:{derivative_role}")[:32],
        workflow_id=envelope.workflow_id,
        stage_revision=envelope.stage_revision,
        occurrence_id="character-1" if is_character else "product-1",
        parent=ParentNodeSnapshotV1(
            node_id=node.node_id,
            node_revision=node.revision,
            semantic_role="character_main" if is_character else "product_main",
            prompt_preparation_operation_id=prompt_operation_id,
        ),
        derivative_role=derivative_role,
        payload_digest=_digest(
            f"{envelope.workflow_id}:{node.node_id}:{node.revision}:"
            f"{prompt_operation_id}:{derivative_role}"
        ),
    )


def _world_setting_node(
    envelope: ProposalApplicationEnvelopeV1,
    value: Any,
) -> CanvasNodeV2:
    result = WorldSettingMaterializationResultV1.model_validate(value)
    document = WorldSettingDocumentV2(
        content=result.structured_content.content,
        core=result.structured_content.core,
        authoring_provenance=WorldSettingAuthoringProvenanceV2(
            source_proposal_id=envelope.proposal_id,
            source_option_id=envelope.selected_option.option_id,
            materialization_run_id=envelope.materialization_id,
            style_skill_run_id=envelope.style_skill_run_id,
            creative_direction_snapshot_id=None,
        ),
    )
    digest = _digest(result.summary_prompt)
    return CanvasNodeV2(
        node_id=f"node_{_digest(envelope.materialization_id)[:32]}",
        workflow_id=envelope.workflow_id,
        node_type="text",
        creative_role="world_setting",
        title=result.title,
        status="ready",
        summary_prompt=result.summary_prompt,
        structured_content=document.model_dump(mode="json"),
        position=CanvasPositionV2(x=0, y=0),
        revision=1,
        prompt_preparation=NodePromptPreparationV1(
            status="ready",
            operation_id=None,
            attempt_no=0,
            context_snapshot_id=envelope.context_snapshot_id,
            prompt_digest=digest,
            updated_at=envelope.created_at,
        ),
        created_at=envelope.created_at,
        updated_at=envelope.created_at,
    )


def _reference_intents(
    envelope: ProposalApplicationEnvelopeV1,
) -> tuple[DraftReferenceIntentV2, ...]:
    return tuple(
        DraftReferenceIntentV2.model_validate(
            reference.model_dump(
                include={
                    "source_kind",
                    "source_id",
                    "binding_kind",
                    "input_role",
                    "required",
                    "display_order",
                    "semantic_reference_role",
                }
            )
        )
        for reference in envelope.reference_plan.references
    )


def _has_storyboard_visual_reference(envelope: ProposalApplicationEnvelopeV1) -> bool:
    return any(
        reference.semantic_reference_role == "storyboard_visual_reference"
        for reference in envelope.reference_plan.references
    )


def _stage_parameters(
    capability_id: str,
    draft_key: str,
    context: CapabilityMaterializationContextV1,
) -> dict[str, object]:
    parameters: dict[str, object] = {"stage_draft_key": draft_key}
    if capability_id == "video_direction":
        duration = context.capability_facts.get("duration_seconds")
        if duration is None:
            total_duration = _explicit_constraint(context, "duration_seconds")
            segment_count = _explicit_constraint(context, "video_segment_count")
            if (
                isinstance(total_duration, (int, float))
                and not isinstance(total_duration, bool)
                and isinstance(segment_count, int)
                and not isinstance(segment_count, bool)
                and segment_count > 0
            ):
                duration = float(total_duration) / segment_count
        if duration is None:
            duration = 5
        parameters["duration_seconds"] = min(15.0, max(1.0, float(duration)))
        aspect_ratio = _explicit_constraint(context, "aspect_ratio")
        if isinstance(aspect_ratio, str) and aspect_ratio.strip():
            parameters["aspect_ratio"] = aspect_ratio.strip()
    elif capability_id == "bgm_direction":
        duration = context.capability_facts.get("duration_seconds", 30)
        parameters["duration_seconds"] = max(1.0, float(duration))
    return parameters


def _explicit_constraint(
    context: CapabilityMaterializationContextV1,
    field: str,
) -> object | None:
    if field in context.explicit_constraints:
        return context.explicit_constraints[field]
    scoped = context.explicit_constraints.get("required_video_parameters")
    return scoped.get(field) if isinstance(scoped, dict) else None


def _bounded_title(base: str, suffix: str) -> str:
    if base.casefold().endswith(suffix.casefold()):
        return base[:256]
    return f"{base[: max(1, 255 - len(suffix))]} {suffix}"[:256]


def _suffixed_title(value: str, suffix: str) -> str:
    separator = " "
    available = 256 - len(separator) - len(suffix)
    if len(value) <= available:
        return f"{value}{separator}{suffix}"
    return f"{value[: available - 3].rstrip()}...{separator}{suffix}"


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)
