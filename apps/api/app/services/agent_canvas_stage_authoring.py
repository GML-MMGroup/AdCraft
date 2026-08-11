"""Stage-local proposal validation and immediate Draft publication orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
)
from app.schemas.agent_canvas_creative_session import (
    DraftReferenceIntentV2,
    SpecialistDraftV2,
)
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    ProposalPublicationEnvelopeV1,
)
from app.schemas.agent_canvas_progressive_authoring import (
    StageDraftSelectionV1,
    StageDraftSpecV1,
)


@dataclass(frozen=True)
class FoundationDraftPlan:
    selection: StageDraftSelectionV1
    drafts: tuple[SpecialistDraftV2, ...]
    node_ids: tuple[str, ...]
    internal_bindings: tuple[CanvasBindingV2, ...]


class FoundationDraftPublicationService:
    """Compile fixed foundation and stage granularity from one concise option."""

    def build(
        self,
        envelope: ProposalPublicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
        *,
        now: datetime,
    ) -> FoundationDraftPlan:
        definitions = _stage_definitions(envelope.capability_id)
        node_ids = tuple(
            f"node_{_digest(f'{envelope.materialization_id}:{draft_key}')[:32]}"
            for draft_key, *_ in definitions
        )
        references = tuple(
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
        specs: list[StageDraftSpecV1] = []
        drafts: list[SpecialistDraftV2] = []
        for index, (draft_key, node_type, role, title_suffix, identity) in enumerate(definitions):
            title = _bounded_title(envelope.selected_option.title, title_suffix)
            summary = envelope.selected_option.public_summary
            parameters = _stage_parameters(
                envelope.capability_id,
                draft_key,
                context,
            )
            specs.append(
                StageDraftSpecV1(
                    draft_key=draft_key,
                    node_type=node_type,
                    creative_role=role,
                    title=title,
                    summary_prompt=summary,
                    structured_identity=identity,
                    parameters=parameters,
                    reference_intents=tuple(
                        reference.model_copy(update={"display_order": order})
                        for order, reference in enumerate(references)
                    ),
                )
            )
            drafts.append(
                SpecialistDraftV2(
                    title=title,
                    node_type=node_type,
                    creative_role=role,
                    summary_prompt=summary,
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
        internal_bindings = _pair_bindings(
            envelope,
            node_ids=node_ids,
            now=now,
        )
        return FoundationDraftPlan(
            selection=StageDraftSelectionV1(
                workflow_id=envelope.workflow_id,
                proposal_id=envelope.proposal_id,
                option_id=envelope.selected_option.option_id,
                source_turn_id=envelope.action_turn_id,
                expected_session_revision=envelope.expected_session_revision,
                idempotency_key=envelope.idempotency_identity,
                drafts=tuple(specs),
            ),
            drafts=tuple(drafts),
            node_ids=node_ids,
            internal_bindings=internal_bindings,
        )


def _stage_definitions(capability_id: str) -> tuple[tuple[str, str, str, str, dict], ...]:
    definitions = {
        "world_setting": (("world-setting", "text", "world_setting", "World Setting", {}),),
        "product_design": (
            ("product-main", "image", "product", "Main", {"asset_kind": "main"}),
            (
                "product-multi-view",
                "image",
                "product",
                "Multi-view",
                {"asset_kind": "multi_view"},
            ),
        ),
        "prop_design": (("prop", "image", "prop", "Prop", {"asset_kind": "main"}),),
        "character_design": (
            (
                "character-main",
                "image",
                "character",
                "Main",
                {"character_asset_kind": "identity_master"},
            ),
            (
                "character-three-view",
                "image",
                "character",
                "Three-view",
                {"character_asset_kind": "turnaround"},
            ),
        ),
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
        return definitions[capability_id]
    except KeyError as error:
        raise ValueError("stage_content_mismatch") from error


def _pair_bindings(
    envelope: ProposalPublicationEnvelopeV1,
    *,
    node_ids: tuple[str, ...],
    now: datetime,
) -> tuple[CanvasBindingV2, ...]:
    if envelope.capability_id not in {"product_design", "character_design"}:
        return ()
    return (
        CanvasBindingV2(
            binding_id=(
                "binding_" + _digest(f"{envelope.materialization_id}:main-to-secondary")[:32]
            ),
            workflow_id=envelope.workflow_id,
            source=CanvasBindingSourceNodeV2(source_node_id=node_ids[0]),
            target_node_id=node_ids[1],
            input_role="image_reference",
            required=True,
            order=0,
            label="Required main reference",
            metadata={"semantic_reference_role": "subject_reference"},
            created_at=now,
            updated_at=now,
        ),
    )


def _stage_parameters(
    capability_id: str,
    draft_key: str,
    context: CapabilityMaterializationContextV1,
) -> dict[str, object]:
    parameters: dict[str, object] = {"stage_draft_key": draft_key}
    if capability_id == "video_direction":
        duration = context.capability_facts.get("duration_seconds", 5)
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


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
