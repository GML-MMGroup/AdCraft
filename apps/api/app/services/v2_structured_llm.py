"""Compatibility error contracts for the removed direct Python LLM client."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.schemas.v2_structured_llm import V2StructuredLLMCallMetadata
from app.services.v2_structured_generation_errors import V2StructuredLLMError


@dataclass(frozen=True)
class V2StructuredLLMResult:
    """Legacy result shape retained only for test and import compatibility."""

    output: BaseModel
    warnings: list[dict[str, Any]]
    call_metadata: V2StructuredLLMCallMetadata | None = None


__all__ = ["V2StructuredLLMError", "V2StructuredLLMResult"]
