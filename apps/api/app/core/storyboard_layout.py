"""Shared Storyboard layout policy; accepted panel counts remain authoritative."""

from collections.abc import Sequence
from typing import Literal

StoryboardPanelCount = Literal[4, 9]


def storyboard_panel_count(duration_seconds: float | None) -> StoryboardPanelCount:
    """Select the layout for new authoring; unspecified timing retains nine panels."""
    return 4 if duration_seconds == 4 else 9


def storyboard_grid_size(panel_count: int) -> Literal[2, 3]:
    if panel_count not in (4, 9):
        raise ValueError("Storyboard layouts require exactly four or nine panels.")
    return 2 if panel_count == 4 else 3


def storyboard_layout_name(panel_count: int) -> str:
    size = storyboard_grid_size(panel_count)
    return f"{size}x{size}"


def validate_storyboard_panel_indices(indices: Sequence[int]) -> None:
    storyboard_grid_size(len(indices))
    if list(indices) != list(range(1, len(indices) + 1)):
        raise ValueError("Storyboard panels must follow contiguous reading order from one.")
