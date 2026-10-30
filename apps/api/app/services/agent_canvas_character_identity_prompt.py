"""Compile character equivalence from frozen inputs and delivered image labels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.agent_canvas import ResolvedInputSnapshotV2, ResolvedMediaInputSnapshotV2


@dataclass(frozen=True, slots=True)
class LabeledIdentityReference:
    label: str
    binding_id: str | None
    asset_id: str
    version_id: str | None
    checksum: str | None
    source_semantic_role: str | None


_CHARACTER_CONTINUITY = (
    "Character identity continuity: When characters appear, each character has one physical "
    "body at one location at a given time within a continuous scene. Preserve each "
    "character's own face or head features, hair, wardrobe, body shape and distinguishing "
    "details across views and cuts, except for explicitly approved story changes. "
    "Distinct character identities remain distinct, even when their approved appearance "
    "is similar; do not merge identities, average their faces, swap their features or "
    "replace one with a copy of another. Front, side and back views within one character "
    "reference, and repeated appearances across storyboard panels, are depictions of the "
    "same character, not additional cast members. Reconcile them with the written cast. "
    "Keep each shot's foreground/background positions, shoulder and hand ownership, "
    "eyelines and movement continuous. A change of view shows the same physical character; "
    "do not retain a copy at the previous position or combine character placements from "
    "different panels into one frame. An intentional mirror or screen depiction refers "
    "to its character, not another physical body. Reference availability does not require "
    "every character to appear in every shot."
)


def compile_character_identity_prompt(
    resolved_inputs: Sequence[ResolvedInputSnapshotV2],
    references: Sequence[LabeledIdentityReference],
    *,
    has_storyboard: bool = False,
) -> str:
    """Group explicit occurrences only; unknown mappings never invent cast identities."""

    snapshots = {
        (item.binding_id, item.asset_id, item.asset_version_id, item.asset_checksum): item
        for item in resolved_inputs
        if isinstance(item, ResolvedMediaInputSnapshotV2) and item.media_type == "image"
    }
    identities: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for reference in references:
        snapshot = snapshots.get(
            (reference.binding_id, reference.asset_id, reference.version_id, reference.checksum)
        )
        if reference.source_semantic_role != "character" and not (
            snapshot is not None
            and (
                snapshot.source_semantic_role == "character"
                or snapshot.binding_metadata.get("semantic_reference_role") == "character_reference"
            )
        ):
            continue
        occurrence_id = _occurrence_id(snapshot) if snapshot is not None else None
        if occurrence_id is None:
            unmapped.append(reference.label)
        else:
            identities.setdefault(occurrence_id, []).append(reference.label)
    if not identities and not unmapped and not has_storyboard:
        return ""
    lines = [_CHARACTER_CONTINUITY]
    if identities:
        lines.append(
            "Character reference mapping (identity groups, not required on-screen counts):"
        )
        for index, labels in enumerate(identities.values(), start=1):
            lines.append(
                f"Character identity {index}: {', '.join(labels)}. These references belong "
                "to this same cast member; preserve its own approved appearance."
            )
        if len(identities) > 1:
            lines.append("Each numbered identity denotes a separate cast member.")
    if unmapped:
        lines.append(
            f"Unmapped character references: {', '.join(unmapped)}. Match them to the written "
            "cast; missing identity metadata does not establish shared identity or extra actors."
        )
    return "\n".join(lines)


def _occurrence_id(snapshot: ResolvedMediaInputSnapshotV2) -> str | None:
    binding_value = snapshot.binding_metadata.get("occurrence_id")
    source_value = snapshot.source_structured_content.get("occurrence_id")
    values = [value for value in (binding_value, source_value) if value is not None]
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        return None
    if len(set(values)) != 1:
        return None
    return values[0]
