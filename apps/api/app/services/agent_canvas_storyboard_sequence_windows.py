"""Deterministic authority for Storyboard Sequence timing windows."""

from __future__ import annotations

from math import ceil, isfinite

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthorityPlanV2,
    StoryboardSequenceWindowV2,
)


class StoryboardSequenceWindowPlanner:
    """Create the immutable platform-owned sequence topology before Agent dispatch."""

    MAX_SEQUENCE_DURATION_SECONDS = 15.0
    MAX_SEQUENCE_COUNT = 128

    @classmethod
    def plan(
        cls,
        *,
        total_duration_seconds: object,
        aspect_ratio: object,
        explicit_sequence_count: object = None,
    ) -> StoryboardSequenceAuthorityPlanV2:
        duration = cls._duration(total_duration_seconds)
        normalized_aspect_ratio = cls._aspect_ratio(aspect_ratio)
        minimum_count = ceil(duration / cls.MAX_SEQUENCE_DURATION_SECONDS)
        if minimum_count > cls.MAX_SEQUENCE_COUNT:
            raise cls._invalid("Storyboard duration requires more than 128 sequences.")

        if explicit_sequence_count is None:
            sequence_count = minimum_count
        elif (
            isinstance(explicit_sequence_count, int)
            and not isinstance(explicit_sequence_count, bool)
            and 1 <= explicit_sequence_count <= cls.MAX_SEQUENCE_COUNT
        ):
            sequence_count = explicit_sequence_count
        else:
            raise cls._invalid("Storyboard sequence count must be an integer from 1 through 128.")
        if sequence_count < minimum_count:
            raise cls._invalid("Storyboard sequence count exceeds the duration policy.")

        boundaries = [0.0]
        boundaries.extend(
            round(duration * ordinal / sequence_count, 3) for ordinal in range(1, sequence_count)
        )
        boundaries.append(duration)
        windows = tuple(
            StoryboardSequenceWindowV2(
                order=ordinal,
                start_seconds=boundaries[ordinal - 1],
                end_seconds=boundaries[ordinal],
            )
            for ordinal in range(1, sequence_count + 1)
        )
        try:
            return StoryboardSequenceAuthorityPlanV2(
                aspect_ratio=normalized_aspect_ratio,
                total_duration_seconds=duration,
                windows=windows,
            )
        except ValueError as error:
            raise cls._invalid("Storyboard sequence windows are invalid.") from error

    @staticmethod
    def _duration(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StoryboardSequenceWindowPlanner._invalid(
                "Storyboard duration must be a finite number."
            )
        duration = float(value)
        if not isfinite(duration) or duration <= 0 or duration > 3_600:
            raise StoryboardSequenceWindowPlanner._invalid(
                "Storyboard duration must be greater than zero and at most 3600 seconds."
            )
        rounded = round(duration, 3)
        if rounded <= 0 or rounded != duration:
            raise StoryboardSequenceWindowPlanner._invalid(
                "Storyboard duration requires millisecond precision."
            )
        return rounded

    @staticmethod
    def _aspect_ratio(value: object) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise StoryboardSequenceWindowPlanner._invalid(
                "Storyboard aspect ratio must be normalized."
            )
        return value

    @staticmethod
    def _invalid(message: str) -> V2PersistenceError:
        return V2PersistenceError(
            "storyboard_sequence_plan_invalid",
            message,
            stage="storyboard_sequence_planning",
        )
