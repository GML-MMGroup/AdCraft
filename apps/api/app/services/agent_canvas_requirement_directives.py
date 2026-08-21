"""Exact canonicalization for active Agent Canvas Requirement directives."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas.agent_canvas_requirements import RequirementDirectiveV1


_SOURCE_AUTHORITY = {
    "accepted_proposal": 1,
    "decision_bundle_answer": 2,
    "user_message": 2,
    "manual_edit": 3,
}


@dataclass(frozen=True)
class RequirementDirectiveCanonicalizationResult:
    active_directives: tuple[RequirementDirectiveV1, ...]
    added_directive_ids: tuple[str, ...]
    superseded_directive_ids: tuple[str, ...]
    duplicate_directive_ids: tuple[str, ...]


def requirement_directive_semantic_identity(
    directive: RequirementDirectiveV1,
) -> str:
    payload = {
        "normalized_meaning": " ".join(
            unicodedata.normalize("NFKC", directive.normalized_meaning).split()
        ).casefold(),
        "scope_kind": directive.scope_kind,
        "capability_ids": sorted(set(directive.capability_ids)),
        "target_node_ids": sorted(set(directive.target_node_ids)),
        "strength": directive.strength,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonicalize_requirement_directives(
    existing_directives: Iterable[RequirementDirectiveV1],
    candidate_directives: Iterable[RequirementDirectiveV1] = (),
    *,
    directive_ids_to_supersede: Iterable[str] = (),
) -> RequirementDirectiveCanonicalizationResult:
    existing = tuple(existing_directives)
    candidates = tuple(candidate_directives)
    _ensure_unique_directive_ids((*existing, *candidates))

    explicitly_removed = frozenset(directive_ids_to_supersede)
    existing_ids = {item.directive_id for item in existing}
    grouped: dict[str, list[RequirementDirectiveV1]] = {}
    for item in (*existing, *candidates):
        if item.directive_id in explicitly_removed:
            continue
        grouped.setdefault(requirement_directive_semantic_identity(item), []).append(item)

    representatives: list[tuple[str, RequirementDirectiveV1]] = []
    duplicate_ids: list[str] = []
    for semantic_identity, group in grouped.items():
        winner = min(
            group,
            key=lambda item: (
                -_SOURCE_AUTHORITY[item.source_kind],
                item.created_revision_no,
                item.directive_id,
            ),
        )
        representatives.append((semantic_identity, winner))
        duplicate_ids.extend(item.directive_id for item in group if item != winner)

    active = tuple(
        item
        for _, item in sorted(
            representatives,
            key=lambda pair: (pair[0], pair[1].directive_id),
        )
    )
    active_ids = {item.directive_id for item in active}
    superseded = sorted((existing_ids & explicitly_removed) | (existing_ids - active_ids))
    added = sorted(item.directive_id for item in candidates if item.directive_id in active_ids)
    return RequirementDirectiveCanonicalizationResult(
        active_directives=active,
        added_directive_ids=tuple(added),
        superseded_directive_ids=tuple(superseded),
        duplicate_directive_ids=tuple(sorted(set(duplicate_ids))),
    )


def _ensure_unique_directive_ids(
    directives: Iterable[RequirementDirectiveV1],
) -> None:
    seen: set[str] = set()
    for directive in directives:
        if directive.directive_id in seen:
            raise ValueError(f"Duplicate Requirement directive ID: {directive.directive_id}")
        seen.add(directive.directive_id)
