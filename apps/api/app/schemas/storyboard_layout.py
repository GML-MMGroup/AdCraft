"""Exact supported Storyboard cardinalities, including generated JSON schemas."""

from typing import Annotated, TypeAlias, TypeVar

from pydantic import Field

_Panel = TypeVar("_Panel")
StoryboardPanels: TypeAlias = (
    Annotated[tuple[_Panel, ...], Field(min_length=4, max_length=4)]
    | Annotated[tuple[_Panel, ...], Field(min_length=9, max_length=9)]
)
