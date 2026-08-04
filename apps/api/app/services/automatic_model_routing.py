"""Deterministically resolve provider-neutral Automatic Audio model policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.persistence.errors import V2PersistenceError
from app.persistence.provider_model_repository import ProviderModelRecord


class AutomaticModelRoutingService:
    """Choose one concrete compatible Audio model without provider access."""

    def resolve(
        self,
        *,
        preferred: ProviderModelRecord,
        node_type: str,
        parameters: Mapping[str, object],
        candidates: Sequence[ProviderModelRecord],
    ) -> ProviderModelRecord:
        if node_type != "audio":
            raise _error(
                "model_automatic_policy_unsupported",
                "Automatic model routing is currently supported only for Audio Nodes.",
                node_type=node_type,
            )
        duration_seconds = _duration_seconds(parameters, required=True)
        eligible = tuple(
            candidate
            for candidate in candidates
            if candidate.provider_id == preferred.provider_id
            and candidate.capability == "audio"
            and candidate.availability == "available"
            and _supports_duration(candidate, duration_seconds)
        )
        if _supports_duration(preferred, duration_seconds):
            return preferred
        if not eligible:
            raise _error(
                "model_automatic_selection_unavailable",
                "No compatible Audio model is available from the preferred provider.",
                provider_id=preferred.provider_id,
                duration_seconds=duration_seconds,
            )
        if len(eligible) == 1:
            return eligible[0]
        ranked = [(candidate, _automatic_tier_priority(candidate)) for candidate in eligible]
        if any(priority is None for _, priority in ranked):
            raise _error(
                "model_automatic_selection_unavailable",
                "Automatic Audio routing requires an unambiguous approved tier priority.",
                provider_id=preferred.provider_id,
                duration_seconds=duration_seconds,
            )
        highest_priority = min(int(priority) for _, priority in ranked if priority is not None)
        winners = [candidate for candidate, priority in ranked if priority == highest_priority]
        if len(winners) != 1:
            raise _error(
                "model_automatic_selection_unavailable",
                "Automatic Audio routing found ambiguous compatible model tiers.",
                provider_id=preferred.provider_id,
                duration_seconds=duration_seconds,
            )
        return winners[0]


def validate_audio_model_parameters(
    record: ProviderModelRecord,
    parameters: Mapping[str, object],
) -> None:
    """Validate explicit Audio parameters against trusted model metadata."""

    duration_seconds = _duration_seconds(parameters, required=False)
    if duration_seconds is None:
        return
    if not _supports_duration(record, duration_seconds):
        raise _error(
            "model_parameter_unsupported",
            "The selected Audio model does not support the requested duration.",
            model_ref=record.model_ref,
            duration_seconds=duration_seconds,
        )


def _duration_seconds(parameters: Mapping[str, object], *, required: bool) -> int | None:
    value = parameters.get("duration_seconds")
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error(
            "model_parameter_unsupported",
            "Audio duration_seconds must be a positive integer.",
        )
    return value


def _supports_duration(record: ProviderModelRecord, duration_seconds: int) -> bool:
    duration_range = record.capability_metadata.get("duration_range_seconds")
    if not isinstance(duration_range, list) or len(duration_range) != 2:
        return False
    minimum, maximum = duration_range
    return (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and minimum >= 1
        and minimum <= maximum
        and minimum <= duration_seconds <= maximum
    )


def _automatic_tier_priority(record: ProviderModelRecord) -> int | None:
    value: Any = record.capability_metadata.get("automatic_tier_priority")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def _error(code: str, message: str, **details: object) -> V2PersistenceError:
    error = V2PersistenceError(code, message, stage="automatic_model_routing")
    error.details = details
    return error
