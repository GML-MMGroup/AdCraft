"""Bounded internal execution-mode values for Agent Canvas runs."""

from typing import Literal


CanvasExecutionModeV2 = Literal["manual_prompt_direct", "agent_assisted"]
CanvasSemanticExtractionModeV2 = Literal["not_required", "agent"]
CanvasParameterSourceV2 = Literal["manual", "typed_binding", "model_default", "mixed"]
