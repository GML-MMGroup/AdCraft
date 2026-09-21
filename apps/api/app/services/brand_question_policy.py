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
    missing_required_slots,
    resolve_slot,
    slot_value_kind,
    validate_slot_values,
)


def validate_question_output(
    output: BrandStrategyOutputV1,
    stage: BrandStage,
    context: BrandQuestionContext,
    values: tuple[BrandSlotValueV1, ...],
    *,
    delegated: frozenset[tuple[str, str]] = frozenset(),
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
        if card is not None:
            raise _invalid_target()
        return tuple(changed)
    if card is None or card.stage != stage or card.target_slot_id is None:
        raise _invalid_target()
    slot = resolve_slot(stage, card.target_slot_id)
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
