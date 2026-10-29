"""Shared authority for compiler-owned revisions and immutable recovery."""

from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_video_parameters import (
    CanvasParameterProvenanceV2,
    CompiledVideoParametersV2,
    VideoParameterCompilationSnapshotV2,
)
from app.services.agent_canvas_prompt_projection_lag import (
    normalize_derived_parameter_prompt_authority,
)


def compiled_parameters_from_snapshot(
    snapshot: VideoParameterCompilationSnapshotV2,
) -> CompiledVideoParametersV2:
    return CompiledVideoParametersV2(
        authoring_parameters=snapshot.authoring_parameters or snapshot.requested_parameters,
        requested_parameters=snapshot.requested_parameters,
        effective_parameters=snapshot.effective_parameters,
        parameter_provenance=snapshot.parameter_provenance,
        accepted_candidates=snapshot.accepted_candidates,
        rejected_lower_priority_candidates=snapshot.rejected_lower_priority_candidates,
        normalizations=snapshot.normalizations,
        parameter_compilation_snapshot_id=snapshot.snapshot_id,
        parameter_source=snapshot.parameter_source,
    )


def parameter_compilation_revision_is_current(
    original: CanvasNodeV2,
    current: CanvasNodeV2,
    compiled: CompiledVideoParametersV2,
) -> bool:
    """Allow only the compiler's own derived-parameter revision bump."""

    if current.revision not in {original.revision, original.revision + 1}:
        return False
    if current.revision != original.revision:
        original = normalize_derived_parameter_prompt_authority(original)
    for field in (
        "node_id",
        "workflow_id",
        "node_type",
        "creative_role",
        "role_contract_version",
        "title",
        "status",
        "execution_mode",
        "summary_prompt",
        "generation_prompt",
        "structured_content",
        "model_selection_mode",
        "model_ref",
        "metadata",
        "prompt_context_snapshot_id",
        "output_asset_id",
        "position",
        "error",
        "prompt_preparation",
    ):
        if getattr(current, field) != getattr(original, field):
            return False
    if current.revision == original.revision:
        return (
            current.parameters == original.parameters
            and current.parameter_provenance == original.parameter_provenance
        )
    return (
        current.parameters == compiled.authoring_parameters
        and _manual_authority_provenance(current) == compiled.parameter_provenance
    )


def _manual_authority_provenance(
    node: CanvasNodeV2,
) -> dict[str, CanvasParameterProvenanceV2]:
    """Read Node provenance with the resolver's manual-authority default.

    Deterministic parameters can be authored without a provenance entry, and
    the parameter resolver treats every such value as manual authority.  The
    compiler's own derived write preserves those values without inventing an
    entry, so the two projections must be compared through the same rule.
    """

    provenance: dict[str, CanvasParameterProvenanceV2] = {}
    for field, value in node.parameters.items():
        entry = node.parameter_provenance.get(field)
        if entry is None:
            if not isinstance(value, (str, int, float, bool)):
                continue
            entry = CanvasParameterProvenanceV2(
                origin="manual",
                requested_value=value,
                effective_value=value,
            )
        provenance[field] = entry
    return provenance
