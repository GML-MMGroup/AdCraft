"""Deterministic evidence and information-gap validation for Brand questions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    BrandSlotEvidenceV1,
    BrandSlotValueV1,
    BrandStage,
    BrandStrategyOutputV1,
)
from app.services.brand_question_context import BrandQuestionContext
from app.services.brand_slot_schema import (
    BrandSlotDefinition,
    missing_required_slots,
    resolve_slot,
    slot_value_kind,
    slots_for_stage,
    validate_slot_values,
)


def validate_question_output(
    output: BrandStrategyOutputV1,
    stage: BrandStage,
    context: BrandQuestionContext,
    values: tuple[BrandSlotValueV1, ...],
    *,
    delegated: frozenset[tuple[str, str]] = frozenset(),
    asked_optional_slots: frozenset[str] = frozenset(),
) -> tuple[BrandSlotValueV1, ...]:
    """Validate all updates and the final target before any persistence writes."""
    validate_slot_values(output.slot_values)
    known = {(value.stage, value.slot_id): value for value in values}
    evidence = {(item.stage, item.slot_id): item for item in output.slot_evidence}
    if len(evidence) != len(output.slot_evidence):
        raise _invalid_evidence()
    sources = {source["source_id"]: source for source in context.payload["user_sources"]}
    changed: list[BrandSlotValueV1] = []
    seen: set[tuple[str, str]] = set()
    for value in output.slot_values:
        key = (value.stage, value.slot_id)
        if key in seen or value.stage not in {"brand-memory", "campaign"}:
            raise _invalid_evidence()
        seen.add(key)
        previous = known.get(key)
        if previous and previous.value == value.value and previous.provenance == value.provenance:
            continue
        if value.provenance == "user_confirmed":
            _validate_evidence(evidence.get(key), sources, previous)
        elif previous and previous.provenance == "user_confirmed":
            raise _invalid_evidence()
        slot = resolve_slot(value.stage, value.slot_id)
        validated = value.model_copy(
            update={
                "confirmed_at": None,
                "kind": slot_value_kind(slot, value.provenance),
            }
        )
        changed.append(validated)
        known[key] = validated
    clarification_keys = set()
    for clarification in output.clarifications:
        key = (clarification.stage, clarification.slot_id)
        resolve_slot(*key)
        if key in seen or clarification.stage != stage:
            raise _invalid_evidence()
        _validate_evidence(clarification, sources, known.get(key))
        clarification_keys.add(key)
    missing = unresolved_required_slots(stage, tuple(known.values()), delegated)
    card = output.question_card
    if not missing and not clarification_keys:
        if card is None:
            if output.question_impact is not None:
                raise _invalid_target()
            return tuple(changed)
        if card.stage != stage or card.target_slot_id is None:
            raise _invalid_target()
        slot = _question_slot(stage, card.target_slot_id)
        key = (stage, slot.slot_id)
        existing = known.get(key)
        impact = output.question_impact
        settled_ids = {
            value.slot_id
            for value in known.values()
            if value.provenance == "user_confirmed" or (value.stage, value.slot_id) in delegated
        }
        if (
            slot.required
            or impact is None
            or not impact.reason.strip()
            or not set(impact.basis_slot_ids) <= settled_ids
            or slot.slot_id in impact.basis_slot_ids
            or key in delegated
            or (existing and existing.provenance == "user_confirmed")
            or slot.slot_id in asked_optional_slots
            or len(asked_optional_slots) >= 2
        ):
            raise _invalid_target()
        return tuple(changed)
    if output.question_impact is not None:
        raise _invalid_target()
    if card is None or card.stage != stage or card.target_slot_id is None:
        raise _invalid_target()
    slot = _question_slot(stage, card.target_slot_id)
    key = (stage, slot.slot_id)
    existing = known.get(key)
    if key not in clarification_keys and slot.slot_id not in missing:
        raise _invalid_target()
    if key not in clarification_keys and (
        key in delegated or (existing and existing.provenance == "user_confirmed")
    ):
        raise _invalid_target()
    if clarification_keys and key not in clarification_keys:
        raise _invalid_target()
    return tuple(changed)


def _question_slot(stage: BrandStage, slot_id: str) -> BrandSlotDefinition:
    try:
        return resolve_slot(stage, slot_id)
    except V2PersistenceError as error:
        raise _invalid_target() from error


def optional_question_targets(
    stage: BrandStage,
    values: tuple[BrandSlotValueV1, ...],
    delegated: frozenset[tuple[str, str]],
    asked: frozenset[str],
) -> tuple[str, ...]:
    if len(asked) >= 2:
        return ()
    settled = {
        value.slot_id
        for value in values
        if value.stage == stage and value.provenance == "user_confirmed"
    }
    settled.update(slot for item_stage, slot in delegated if item_stage == stage)
    return tuple(
        slot.slot_id
        for slot in slots_for_stage(stage)
        if not slot.required and slot.slot_id not in settled | asked
    )


def unresolved_required_slots(
    stage: BrandStage,
    values: tuple[BrandSlotValueV1, ...],
    delegated: frozenset[tuple[str, str]],
) -> tuple[str, ...]:
    return tuple(
        slot for slot in missing_required_slots(stage, values) if (stage, slot) not in delegated
    )


def _validate_evidence(
    evidence: BrandSlotEvidenceV1 | None,
    sources: dict[str, dict[str, Any]],
    previous: BrandSlotValueV1 | None,
) -> None:
    if evidence is None:
        raise _invalid_evidence()
    source = sources.get(evidence.source_id)
    if (
        source is None
        or not evidence.source_quote.strip()
        or evidence.source_quote not in source["text"]
    ):
        raise _invalid_evidence()
    if previous and previous.confirmed_at is not None:
        created_at = datetime.fromisoformat(source["created_at"].replace("Z", "+00:00"))
        if created_at <= previous.confirmed_at:
            raise _invalid_evidence()


def _invalid_evidence() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_slot_evidence_invalid",
        "Brand slot updates require current explicit user evidence.",
        stage="brand_question_policy",
    )


def _invalid_target() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_question_target_invalid",
        "The Brand question must address a remaining information gap.",
        stage="brand_question_policy",
    )
