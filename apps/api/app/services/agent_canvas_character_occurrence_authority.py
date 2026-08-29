"""Deterministic Character occurrence cardinality and identity authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.agent_canvas_requirements import (
    CharacterCountControlV1,
    CharacterOccurrencePatchV1,
    CharacterOccurrenceV1,
    ManualCharacterOccurrencePatchV1,
    RequirementApplicationDeltaV1,
    RequirementElementPresenceV1,
    RequirementLedgerV1,
    RequirementSourceKindV1,
)


CharacterOccurrenceAuthorityPatch = (
    CharacterOccurrencePatchV1 | ManualCharacterOccurrencePatchV1 | CharacterOccurrenceV1
)
CharacterOccurrenceAuthorityStatus = Literal["resolved_zero", "resolved_positive", "unresolved"]


class CharacterOccurrenceAuthorityError(ValueError):
    """A stable, redacted Character occurrence authority failure."""

    def __init__(self, code: str, message: str, *, details: dict[str, object]) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class CharacterOccurrenceAuthoritySource:
    """Typed source lineage used only when reconciliation derives a field."""

    source_kind: RequirementSourceKindV1
    source_text: str
    source_turn_id: str | None = None
    source_proposal_id: str | None = None
    source_bundle_id: str | None = None
    source_question_id: str | None = None
    source_option_id: str | None = None
    source_node_id: str | None = None


@dataclass(frozen=True)
class CharacterOccurrenceAuthorityProjection:
    status: CharacterOccurrenceAuthorityStatus
    occurrences: tuple[CharacterOccurrenceV1, ...]


@dataclass(frozen=True)
class CharacterOccurrenceReconciliationResult:
    ledger: RequirementLedgerV1
    projection: CharacterOccurrenceAuthorityProjection
    delta: RequirementApplicationDeltaV1


def reconcile_character_occurrence_authority(
    current: RequirementLedgerV1,
    candidate: RequirementLedgerV1,
    *,
    occurrence_patches: tuple[CharacterOccurrenceAuthorityPatch, ...] | None,
    revision_no: int,
    source: CharacterOccurrenceAuthoritySource,
    explicit_character_count: bool,
    explicit_character_presence: bool,
    protected_occurrence_ids: frozenset[str] = frozenset(),
) -> CharacterOccurrenceReconciliationResult:
    """Reconcile one candidate Ledger without persistence or external work."""

    validate_character_occurrence_authority(current)
    candidate_count = _character_count(candidate)
    candidate_presence = _character_presence(candidate)
    _validate_incoming_facts(
        count=candidate_count,
        presence=candidate_presence,
        occurrence_patches=occurrence_patches,
        explicit_character_count=explicit_character_count,
        explicit_character_presence=explicit_character_presence,
    )

    if occurrence_patches is None:
        roster = list(current.character_occurrences)
    else:
        roster = list(
            _canonicalize_occurrence_patches(
                current.character_occurrences,
                occurrence_patches,
                revision_no=revision_no,
            )
        )

    target_count = _target_count(
        candidate_count=candidate_count,
        candidate_presence=candidate_presence,
        occurrence_patches=occurrence_patches,
        explicit_character_count=explicit_character_count,
        explicit_character_presence=explicit_character_presence,
        current_occurrences=current.character_occurrences,
        roster=tuple(roster),
    )
    if target_count is not None:
        roster = _resize_roster(
            current=current.character_occurrences,
            roster=roster,
            target_count=target_count,
            revision_no=revision_no,
            protected_occurrence_ids=protected_occurrence_ids,
            explicit_occurrences=occurrence_patches is not None,
        )

    synchronized = _synchronize_ledger_fields(
        candidate,
        roster=tuple(roster),
        target_count=target_count,
        revision_no=revision_no,
        source=source,
    )
    projection = validate_character_occurrence_authority(synchronized)
    delta = _reconciliation_delta(current.character_occurrences, tuple(roster))
    return CharacterOccurrenceReconciliationResult(
        ledger=synchronized,
        projection=projection,
        delta=delta,
    )


def validate_character_occurrence_authority(
    ledger: RequirementLedgerV1,
) -> CharacterOccurrenceAuthorityProjection:
    """Validate complete persisted authority and return its Journey projection."""

    occurrences = ledger.character_occurrences
    occurrence_ids = tuple(item.occurrence_id for item in occurrences)
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise _mismatch("duplicate_occurrence_id")
    occurrence_indexes = tuple(item.occurrence_index for item in occurrences)
    if occurrence_indexes != tuple(range(1, len(occurrences) + 1)):
        raise _mismatch("non_contiguous_occurrence_index")

    count_controls = tuple(
        item for item in ledger.hard_controls if item.control == "character_count"
    )
    if len(count_controls) > 1:
        raise _mismatch("duplicate_character_count")
    presences = tuple(item for item in ledger.element_presence if item.element_kind == "character")
    if len(presences) > 1:
        raise _mismatch("duplicate_character_presence")

    included = tuple(item for item in occurrences if item.presence == "include")
    count = count_controls[0].value if count_controls else None
    presence = presences[0] if presences else None
    if count is not None:
        if len(included) != count:
            raise _mismatch(
                "included_count_mismatch",
                character_count=count,
                included_occurrence_count=len(included),
            )
        expected_presence = "include" if count > 0 else "exclude"
        if presence is None or presence.presence != expected_presence:
            raise _mismatch(
                "presence_count_mismatch",
                character_count=count,
                character_presence=(presence.presence if presence is not None else "missing"),
            )
        return CharacterOccurrenceAuthorityProjection(
            status="resolved_positive" if count > 0 else "resolved_zero",
            occurrences=included,
        )

    if presence is not None and presence.presence in {"exclude", "unspecified"} and included:
        raise _mismatch(
            "presence_roster_mismatch",
            character_presence=presence.presence,
            included_occurrence_count=len(included),
        )
    if included:
        return CharacterOccurrenceAuthorityProjection(
            status="resolved_positive",
            occurrences=included,
        )
    if presence is not None and presence.presence == "exclude":
        return CharacterOccurrenceAuthorityProjection(status="resolved_zero", occurrences=())
    if presence is not None and presence.presence == "include":
        compatibility = CharacterOccurrenceV1(
            occurrence_id="character-1",
            occurrence_index=1,
            role="Character",
            identity_summary=presence.source_text,
            presence="include",
            source_revision_no=presence.created_revision_no,
            specification_state="specified",
        )
        return CharacterOccurrenceAuthorityProjection(
            status="resolved_positive",
            occurrences=(compatibility,),
        )
    return CharacterOccurrenceAuthorityProjection(status="unresolved", occurrences=())


def _validate_incoming_facts(
    *,
    count: int | None,
    presence: str | None,
    occurrence_patches: tuple[CharacterOccurrenceAuthorityPatch, ...] | None,
    explicit_character_count: bool,
    explicit_character_presence: bool,
) -> None:
    if explicit_character_count and count is not None and explicit_character_presence:
        expected = "include" if count > 0 else "exclude"
        if presence != expected:
            raise _conflict(
                "presence_count_conflict",
                character_count=count,
                character_presence=presence or "missing",
            )
    if occurrence_patches is None:
        return
    included_count = sum(item.presence == "include" for item in occurrence_patches)
    if explicit_character_count and count is not None and included_count > count:
        raise _conflict(
            "occurrence_count_conflict",
            character_count=count,
            included_occurrence_count=included_count,
        )
    if explicit_character_presence and presence in {"exclude", "unspecified"} and included_count:
        raise _conflict(
            "presence_roster_conflict",
            character_presence=presence,
            included_occurrence_count=included_count,
        )
    if explicit_character_presence and presence == "include" and not occurrence_patches:
        raise _conflict(
            "presence_roster_conflict",
            character_presence=presence,
            included_occurrence_count=0,
        )


def _target_count(
    *,
    candidate_count: int | None,
    candidate_presence: str | None,
    occurrence_patches: tuple[CharacterOccurrenceAuthorityPatch, ...] | None,
    explicit_character_count: bool,
    explicit_character_presence: bool,
    current_occurrences: tuple[CharacterOccurrenceV1, ...],
    roster: tuple[CharacterOccurrenceV1, ...],
) -> int | None:
    if explicit_character_count:
        return candidate_count
    if occurrence_patches is not None:
        if (
            occurrence_patches
            and candidate_count is not None
            and any(
                item.specification_state == "reserved"
                and item.occurrence_index > len(occurrence_patches)
                for item in current_occurrences
            )
        ):
            return candidate_count
        return sum(item.presence == "include" for item in occurrence_patches)
    if candidate_count is not None:
        return candidate_count
    if explicit_character_presence:
        if candidate_presence == "exclude":
            return 0
        if candidate_presence == "include":
            if candidate_count is not None:
                return candidate_count
            included = sum(item.presence == "include" for item in roster)
            return included or 1
        return None
    return None


def _canonicalize_occurrence_patches(
    current: tuple[CharacterOccurrenceV1, ...],
    patches: tuple[CharacterOccurrenceAuthorityPatch, ...],
    *,
    revision_no: int,
) -> tuple[CharacterOccurrenceV1, ...]:
    current_by_index = {item.occurrence_index: item for item in current}
    current_by_identity = {_identity(item.role, item.identity_summary): item for item in current}
    used_ids: set[str] = set()
    next_id = _next_numeric_id(current)
    result: list[CharacterOccurrenceV1] = []
    for patch in patches:
        if isinstance(patch, CharacterOccurrenceV1):
            prior = next(
                (item for item in current if item.occurrence_id == patch.occurrence_id),
                None,
            )
            result.append(
                patch
                if prior == patch
                else patch.model_copy(update={"source_revision_no": revision_no})
            )
            used_ids.add(patch.occurrence_id)
            continue
        role = " ".join(patch.role.split())
        summary = " ".join(patch.identity_summary.split())
        at_index = current_by_index.get(patch.occurrence_index)
        by_identity = current_by_identity.get(_identity(role, summary))
        existing = None
        if at_index is not None and (
            at_index.specification_state == "reserved"
            or _identity(at_index.role, at_index.identity_summary) == _identity(role, summary)
        ):
            existing = at_index
        elif by_identity is not None and by_identity.occurrence_id not in used_ids:
            existing = by_identity
        if existing is None:
            occurrence_id, next_id = _allocate_id(current, used_ids, next_id)
            source_revision_no = revision_no
        else:
            occurrence_id = existing.occurrence_id
            source_revision_no = (
                existing.source_revision_no
                if existing.occurrence_index == patch.occurrence_index
                and existing.role == role
                and existing.identity_summary == summary
                and existing.presence == patch.presence
                and existing.specification_state == "specified"
                else revision_no
            )
        used_ids.add(occurrence_id)
        result.append(
            CharacterOccurrenceV1(
                occurrence_id=occurrence_id,
                occurrence_index=patch.occurrence_index,
                role=role,
                identity_summary=summary,
                presence=patch.presence,
                source_revision_no=source_revision_no,
                specification_state="specified",
            )
        )
    return tuple(result)


def _resize_roster(
    *,
    current: tuple[CharacterOccurrenceV1, ...],
    roster: list[CharacterOccurrenceV1],
    target_count: int,
    revision_no: int,
    protected_occurrence_ids: frozenset[str],
    explicit_occurrences: bool,
) -> list[CharacterOccurrenceV1]:
    included_count = sum(item.presence == "include" for item in roster)
    if explicit_occurrences and included_count > target_count:
        raise _conflict(
            "occurrence_count_conflict",
            character_count=target_count,
            included_occurrence_count=included_count,
        )
    if included_count > target_count:
        keep_through = 0
        seen = 0
        if target_count:
            for index, item in enumerate(roster, start=1):
                if item.presence == "include":
                    seen += 1
                if seen == target_count:
                    keep_through = index
                    break
        removed = roster[keep_through:]
        _require_unprotected_removal(removed, protected_occurrence_ids)
        roster = roster[:keep_through]
        included_count = target_count

    current_by_index = {item.occurrence_index: item for item in current}
    used_ids = {item.occurrence_id for item in roster}
    next_id = _next_numeric_id(current)
    while included_count < target_count:
        index = len(roster) + 1
        existing = current_by_index.get(index)
        if existing is not None and existing.occurrence_id not in used_ids:
            occurrence = existing
        else:
            occurrence_id, next_id = _allocate_id(current, used_ids, next_id)
            occurrence = CharacterOccurrenceV1(
                occurrence_id=occurrence_id,
                occurrence_index=index,
                role=f"Character slot {index}",
                identity_summary=f"Reserved character occurrence {index}.",
                presence="include",
                source_revision_no=revision_no,
                specification_state="reserved",
            )
        roster.append(occurrence)
        used_ids.add(occurrence.occurrence_id)
        included_count += occurrence.presence == "include"

    removed_ids = {item.occurrence_id for item in current} - {item.occurrence_id for item in roster}
    _require_unprotected_removal(
        tuple(item for item in current if item.occurrence_id in removed_ids),
        protected_occurrence_ids,
    )
    return roster


def _synchronize_ledger_fields(
    candidate: RequirementLedgerV1,
    *,
    roster: tuple[CharacterOccurrenceV1, ...],
    target_count: int | None,
    revision_no: int,
    source: CharacterOccurrenceAuthoritySource,
) -> RequirementLedgerV1:
    controls = {item.control: item for item in candidate.hard_controls}
    presences = {item.element_kind: item for item in candidate.element_presence}
    if target_count is not None:
        existing_count = controls.get("character_count")
        if existing_count is None or existing_count.value != target_count:
            controls["character_count"] = CharacterCountControlV1(
                value=target_count,
                source_kind=source.source_kind,
                source_turn_id=source.source_turn_id,
                source_proposal_id=source.source_proposal_id,
                source_bundle_id=source.source_bundle_id,
                source_question_id=source.source_question_id,
                source_option_id=source.source_option_id,
                source_node_id=source.source_node_id,
                source_text=source.source_text,
                created_revision_no=revision_no,
            )
        desired_presence = "include" if target_count > 0 else "exclude"
        existing_presence = presences.get("character")
        if existing_presence is None or existing_presence.presence != desired_presence:
            presences["character"] = RequirementElementPresenceV1(
                element_kind="character",
                presence=desired_presence,
                source_kind=source.source_kind,
                source_turn_id=source.source_turn_id,
                source_bundle_id=source.source_bundle_id,
                source_question_id=source.source_question_id,
                source_option_id=source.source_option_id,
                source_text=source.source_text,
                created_revision_no=revision_no,
            )
    payload = candidate.model_copy(
        update={
            "hard_controls": tuple(controls[key] for key in sorted(controls)),
            "element_presence": tuple(presences[key] for key in sorted(presences)),
            "character_occurrences": roster,
        }
    )
    return RequirementLedgerV1.model_validate(payload.model_dump(mode="json"))


def _reconciliation_delta(
    current: tuple[CharacterOccurrenceV1, ...],
    replacement: tuple[CharacterOccurrenceV1, ...],
) -> RequirementApplicationDeltaV1:
    current_by_id = {item.occurrence_id: item for item in current}
    replacement_ids = {item.occurrence_id for item in replacement}
    changed_ids = tuple(
        item.occurrence_id for item in replacement if current_by_id.get(item.occurrence_id) != item
    )
    superseded_ids = tuple(
        item.occurrence_id for item in current if item.occurrence_id not in replacement_ids
    )
    changed = bool(changed_ids or superseded_ids)
    reserved_ids = tuple(
        item.occurrence_id for item in replacement if item.specification_state == "reserved"
    )
    specified_ids = tuple(
        item.occurrence_id for item in replacement if item.specification_state == "specified"
    )
    return RequirementApplicationDeltaV1(
        changed_character_occurrence_ids=changed_ids,
        superseded_character_occurrence_ids=superseded_ids,
        character_occurrence_count=(len(replacement) if changed else None),
        reserved_character_occurrence_ids=(reserved_ids if changed else ()),
        specified_character_occurrence_ids=(specified_ids if changed else ()),
        reserved_character_occurrence_count=(len(reserved_ids) if changed else None),
        specified_character_occurrence_count=(len(specified_ids) if changed else None),
    )


def _character_count(ledger: RequirementLedgerV1) -> int | None:
    return next(
        (item.value for item in ledger.hard_controls if item.control == "character_count"),
        None,
    )


def _character_presence(ledger: RequirementLedgerV1) -> str | None:
    return next(
        (item.presence for item in ledger.element_presence if item.element_kind == "character"),
        None,
    )


def _identity(role: str, summary: str) -> tuple[str, str]:
    return " ".join(role.split()).casefold(), " ".join(summary.split()).casefold()


def _next_numeric_id(current: tuple[CharacterOccurrenceV1, ...]) -> int:
    return (
        max(
            (
                int(suffix)
                for item in current
                if (suffix := item.occurrence_id.removeprefix("character-")).isdigit()
            ),
            default=0,
        )
        + 1
    )


def _allocate_id(
    current: tuple[CharacterOccurrenceV1, ...],
    used_ids: set[str],
    next_id: int,
) -> tuple[str, int]:
    unavailable = {item.occurrence_id for item in current} | used_ids
    while f"character-{next_id}" in unavailable:
        next_id += 1
    return f"character-{next_id}", next_id + 1


def _require_unprotected_removal(
    removed: tuple[CharacterOccurrenceV1, ...] | list[CharacterOccurrenceV1],
    protected_occurrence_ids: frozenset[str],
) -> None:
    blocked = sorted(
        item.occurrence_id for item in removed if item.occurrence_id in protected_occurrence_ids
    )
    if blocked:
        raise _conflict("protected_occurrence_removal", occurrence_ids=blocked)


def _conflict(reason: str, **details: object) -> CharacterOccurrenceAuthorityError:
    return CharacterOccurrenceAuthorityError(
        "character_occurrence_reconciliation_conflict",
        "Accepted Character count, presence, and occurrence authority conflict.",
        details={"reason": reason, **details, "retryable": False},
    )


def _mismatch(reason: str, **details: object) -> CharacterOccurrenceAuthorityError:
    return CharacterOccurrenceAuthorityError(
        "character_occurrence_cardinality_mismatch",
        "Persisted Character count, presence, and occurrence authority do not match.",
        details={"reason": reason, **details, "retryable": False},
    )
