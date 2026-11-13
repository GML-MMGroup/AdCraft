"""Deterministic authority for Storyboard Sequence timing windows."""

from __future__ import annotations

from math import ceil, isfinite

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthorityPlanV2,
    StoryboardSequenceWindowV2,
)


class StoryboardSequenceWindowPlanner:
    """Bound Agent allocation and validate its windows before freezing topology."""

    MIN_SEQUENCE_DURATION_SECONDS = 4.0
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
        if sequence_count * cls.MIN_SEQUENCE_DURATION_SECONDS > duration:
            raise cls._invalid(
                "Storyboard sequence count requires at least 4 seconds per generation segment."
            )

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
                timing_mode="narrative" if explicit_sequence_count is None else "adaptive",
            )
        except ValueError as error:
            raise cls._invalid("Storyboard sequence windows are invalid.") from error

    @staticmethod
    def accept_authored_windows(
        authority: StoryboardSequenceAuthorityPlanV2,
        windows: tuple[StoryboardSequenceWindowV2, ...],
    ) -> StoryboardSequenceAuthorityPlanV2:
        """Validate without rounding, repartitioning or mutating the request authority."""

        if authority.timing_mode != "narrative" and len(windows) != len(authority.windows):
            raise ValueError("Storyboard outline count does not match authority.")
        if authority.timing_mode == "fixed" and windows != authority.windows:
            raise ValueError("Storyboard outline timing does not match fixed authority.")
        if authority.timing_mode != "fixed":
            if any(
                (duration := round(window.end_seconds - window.start_seconds, 3))
                < StoryboardSequenceWindowPlanner.MIN_SEQUENCE_DURATION_SECONDS
                or not duration.is_integer()
                for window in windows
            ):
                raise ValueError(
                    "Use whole-second generation durations of at least 4 seconds; "
                    "four-panel segments last exactly 4 seconds."
                )
        return StoryboardSequenceAuthorityPlanV2.model_validate(
            {**authority.model_dump(mode="json"), "windows": windows}
        )

    @staticmethod
    def _duration(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StoryboardSequenceWindowPlanner._invalid(
                "Storyboard duration must be a finite number."
            )
        duration = float(value)
        if not isfinite(duration) or duration < 4 or duration > 3_600 or not duration.is_integer():
            raise StoryboardSequenceWindowPlanner._invalid(
                "Storyboard generation requires a whole-second total from 4 through 3600 seconds."
            )
        return duration

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
