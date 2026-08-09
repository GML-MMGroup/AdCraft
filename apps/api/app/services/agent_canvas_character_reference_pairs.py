"""Deterministic Character identity-master and Turnaround pair construction."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
)
from app.schemas.agent_canvas_creative_session import (
    CharacterImageSpecialistDraftV2,
    DraftReferenceIntentV2,
)
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationEnvelopeV1,
    CharacterMaterializationResultV1,
    MaterializationNormalizationV1,
)


_MAIN_PROMPT = """Create one detailed semi-realistic 2D commercial character illustration, clearly illustrated rather than photographed. Show exactly one full-body human in a natural standing pose with a slight three-quarter front view on a seamless light-neutral design background with no environmental objects. Use only a subtle grounding shadow. Preserve readable facial features, hair, wardrobe construction, body proportions, silhouette, and color palette."""

_TURNAROUND_PROMPT = """Use the bound Character Main image as the sole identity master. Render one turnaround sheet with exactly three unlabeled full-body figures arranged left-to-right as forward-facing, exact side profile, and rear-facing on a seamless light-neutral design background. All three views are the same person with identical face, hair, wardrobe, proportions, silhouette, materials, palette, and detailed semi-realistic illustration treatment. Keep the sheet blank: no headings, orientation labels, captions, typography, logos, or watermarks anywhere. Do not reinterpret or redesign the identity."""


@dataclass(frozen=True, slots=True)
class CharacterReferencePairDraftsV1:
    character_pair_id: str
    main_node_id: str
    turnaround_node_id: str
    main_draft: CharacterImageSpecialistDraftV2
    turnaround_draft: CharacterImageSpecialistDraftV2
    internal_binding: CanvasBindingV2


class CharacterReferencePairFactory:
    """Build one complete Character reference pair without I/O or provider work."""

    def build(
        self,
        *,
        envelope: CapabilityMaterializationEnvelopeV1,
        normalization: MaterializationNormalizationV1,
    ) -> CharacterReferencePairDraftsV1:
        main_result = CharacterMaterializationResultV1.model_validate(normalization.result)
        materialization_id = envelope.materialization_id
        pair_id = f"pair_{_digest(materialization_id)[:32]}"
        main_node_id = f"node_{_digest(f'{materialization_id}:main')[:32]}"
        turnaround_node_id = f"node_{_digest(f'{materialization_id}:turnaround')[:32]}"
        binding_id = f"binding_{_digest(f'{materialization_id}:main-to-turnaround')[:32]}"
        common_parameters = {
            **normalization.parameters,
            "normalization_mode": normalization.mode,
            "normalization_warnings": list(normalization.warnings),
            "character_pair_id": pair_id,
        }
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
        main_content = main_result.structured_content.model_copy(
            update={"character_asset_kind": "identity_master"}
        )
        turnaround_content = main_result.structured_content.model_copy(
            update={"character_asset_kind": "turnaround"}
        )
        main = CharacterImageSpecialistDraftV2(
            node_type="image",
            creative_role="character",
            title=main_result.title,
            summary_prompt=main_result.summary_prompt,
            generation_prompt=f"{_MAIN_PROMPT}\n\nIdentity direction: {main_result.generation_prompt}",
            structured_content=main_content,
            parameters={**common_parameters, "character_asset_kind": "identity_master"},
            parameter_provenance=normalization.parameter_provenance,
            prompt_context_snapshot_id=envelope.context_snapshot_id,
            reference_intents=references,
        )
        turnaround = CharacterImageSpecialistDraftV2(
            node_type="image",
            creative_role="character",
            title=f"{main_result.title} Turnaround",
            summary_prompt=f"Three-view unlabeled identity sheet for {main_result.title}.",
            generation_prompt=(
                f"{_TURNAROUND_PROMPT}\n\nIdentity: {main_content.subject_identity}. "
                f"Design: {main_content.design_summary}."
            ),
            structured_content=turnaround_content,
            parameters={**common_parameters, "character_asset_kind": "turnaround"},
            parameter_provenance=normalization.parameter_provenance,
            prompt_context_snapshot_id=envelope.context_snapshot_id,
        )
        binding = CanvasBindingV2(
            binding_id=binding_id,
            workflow_id=envelope.workflow_id,
            source=CanvasBindingSourceNodeV2(source_node_id=main_node_id),
            target_node_id=turnaround_node_id,
            input_role="image_reference",
            required=True,
            enabled=True,
            order=0,
            label="Character identity master",
            metadata={
                "character_pair_id": pair_id,
                "reference_purpose": "identity_master",
                "semantic_reference_role": "subject_reference",
            },
            created_at=envelope.created_at,
            updated_at=envelope.created_at,
        )
        return CharacterReferencePairDraftsV1(
            character_pair_id=pair_id,
            main_node_id=main_node_id,
            turnaround_node_id=turnaround_node_id,
            main_draft=main,
            turnaround_draft=turnaround,
            internal_binding=binding,
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def character_turnaround_prompt(
    *,
    subject_identity: str,
    design_summary: str,
) -> str:
    """Compile the deterministic companion prompt for a varied Character Main."""

    return f"{_TURNAROUND_PROMPT}\n\nIdentity: {subject_identity}. Design: {design_summary}."
