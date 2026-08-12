"""Internal immutable output of capability Draft compilation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.agent_canvas import CanvasBindingV2, CanvasNodeV2
from app.schemas.agent_canvas_materialization_commit import NodePromptPreparationIntentV1


class CapabilityDraftBundleV1(BaseModel):
    """Complete authoring inputs produced before materialization plan assembly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: tuple[CanvasNodeV2, ...]
    bindings: tuple[CanvasBindingV2, ...]
    prompt_preparations: tuple[NodePromptPreparationIntentV1, ...]
