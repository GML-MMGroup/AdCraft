"""Canonical fixed-duration, single-track timeline normalization."""

from __future__ import annotations

from collections.abc import Mapping

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_editing import EditingManifestV2, EditingVideoEntryV2


TIMELINE_EPSILON = 1e-6
SourceKey = tuple[str, str]


def normalize_manifest(
    manifest: EditingManifestV2,
    *,
    current_manifest: EditingManifestV2 | None = None,
    source_durations: Mapping[SourceKey, float] | None = None,
) -> EditingManifestV2:
    """Return a complete manifest without mutating the caller or persistence."""

    durations = source_durations or {}
    current_entries = (
        {entry.source_key: entry for entry in current_manifest.video_entries}
        if current_manifest is not None
        else {}
    )
    current_is_canonical = bool(
        current_manifest is not None
        and current_manifest.timeline_duration_seconds is not None
        and all(
            entry.timeline_start_seconds is not None for entry in current_manifest.video_entries
        )
    )
    timeline_duration = manifest.timeline_duration_seconds
    if timeline_duration is None and current_is_canonical:
        timeline_duration = current_manifest.timeline_duration_seconds
    if timeline_duration is None and manifest.video_entries:
        known_durations = [
            _require_source_duration(entry, durations)
            for entry in manifest.video_entries
            if entry.source_key in durations
        ]
        if len(known_durations) != len(manifest.video_entries):
            raise _timeline_error(
                "editing_timeline_duration_invalid",
                "A fixed Editing timeline duration requires original source durations.",
            )
        timeline_duration = sum(known_durations)
    if timeline_duration is None:
        return manifest
    if timeline_duration <= TIMELINE_EPSILON:
        raise _timeline_error(
            "editing_timeline_duration_invalid",
            "Editing timeline duration must be positive.",
        )

    current_end = _current_end(current_manifest, durations)
    legacy_cursor = 0.0
    normalized_entries: list[EditingVideoEntryV2] = []
    for entry in manifest.video_entries:
        previous = current_entries.get(entry.source_key)
        start = entry.timeline_start_seconds
        if start is None and previous is not None and previous.timeline_start_seconds is not None:
            start = previous.timeline_start_seconds
        elif start is None:
            start = current_end if current_is_canonical else legacy_cursor
        normalized_entries.append(entry.model_copy(update={"timeline_start_seconds": start}))
        duration = durations.get(entry.source_key)
        if duration is not None and duration > TIMELINE_EPSILON:
            if not current_is_canonical:
                legacy_cursor = start + duration
            elif previous is None:
                current_end = max(current_end, start + duration)

    normalized = manifest.model_copy(
        update={
            "timeline_duration_seconds": timeline_duration,
            "video_entries": tuple(normalized_entries),
        }
    )
    _validate_intervals(normalized, durations)
    return normalized


def _validate_intervals(
    manifest: EditingManifestV2,
    source_durations: Mapping[SourceKey, float],
) -> None:
    intervals: list[tuple[float, float, SourceKey]] = []
    timeline_duration = manifest.timeline_duration_seconds
    if timeline_duration is None:
        return
    for entry in manifest.video_entries:
        duration = source_durations.get(entry.source_key)
        if not entry.enabled or duration is None:
            continue
        _require_source_duration(entry, source_durations)
        start = entry.timeline_start_seconds
        if start is None:
            raise _timeline_error(
                "editing_timeline_duration_invalid",
                "Every canonical Editing video entry requires a timeline position.",
            )
        effective_duration = _effective_duration(entry, duration)
        if effective_duration <= TIMELINE_EPSILON:
            raise _timeline_error(
                "editing_timeline_duration_invalid",
                "Every enabled Editing video entry must have positive effective duration.",
            )
        end = start + effective_duration
        if start < -TIMELINE_EPSILON or end > timeline_duration + TIMELINE_EPSILON:
            raise _timeline_error(
                "editing_timeline_out_of_bounds",
                "An enabled Editing video entry falls outside the fixed timeline.",
            )
        intervals.append((start, end, entry.source_key))

    intervals.sort(key=lambda interval: (interval[0], interval[2]))
    for previous, current in zip(intervals, intervals[1:], strict=False):
        if current[0] < previous[1] - TIMELINE_EPSILON:
            raise _timeline_error(
                "editing_timeline_overlap",
                "Enabled Editing video entries cannot overlap.",
            )


def _current_end(
    manifest: EditingManifestV2 | None,
    source_durations: Mapping[SourceKey, float],
) -> float:
    if manifest is None:
        return 0.0
    ends = []
    for entry in manifest.video_entries:
        if entry.timeline_start_seconds is None:
            continue
        duration = source_durations.get(entry.source_key)
        if duration is not None and duration > TIMELINE_EPSILON:
            ends.append(entry.timeline_start_seconds + duration)
    return max(ends, default=0.0)


def _require_source_duration(
    entry: EditingVideoEntryV2,
    source_durations: Mapping[SourceKey, float],
) -> float:
    duration = source_durations.get(entry.source_key)
    if duration is None or duration <= TIMELINE_EPSILON:
        raise _timeline_error(
            "editing_timeline_duration_invalid",
            "Original source media duration is required for Editing timeline validation.",
        )
    return duration


def _effective_duration(entry: EditingVideoEntryV2, source_duration: float) -> float:
    end = entry.trim_end_seconds if entry.trim_end_seconds is not None else source_duration
    if entry.trim_start_seconds >= source_duration or end > source_duration + TIMELINE_EPSILON:
        raise _timeline_error(
            "editing_timeline_duration_invalid",
            "Editing trim range exceeds the original source duration.",
        )
    return end - entry.trim_start_seconds


def _timeline_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_timeline")
