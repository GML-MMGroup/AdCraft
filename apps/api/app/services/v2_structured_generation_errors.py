from __future__ import annotations

from typing import Any, Literal

from app.schemas.v2_structured_llm import V2StructuredLLMCallMetadata


V2StructuredLLMFailureKind = Literal[
    "configuration",
    "provider_transient",
    "provider_terminal",
    "content",
]


class V2StructuredLLMError(RuntimeError):
    """Normalized structured-generation failure used by deterministic fallbacks."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        invalid_output: Any | None = None,
        validation_error_paths: list[str] | None = None,
        quality_error_code: str | None = None,
        quality_error_message: str | None = None,
        quality_error_details: dict[str, Any] | None = None,
        failure_kind: V2StructuredLLMFailureKind | None = None,
        call_metadata: V2StructuredLLMCallMetadata | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.invalid_output = invalid_output
        self.validation_error_paths = validation_error_paths or []
        self.quality_error_code = quality_error_code
        self.quality_error_message = quality_error_message
        self.quality_error_details = quality_error_details or {}
        self.failure_kind = failure_kind or _failure_kind_for_code(code)
        self.call_metadata = call_metadata


def _failure_kind_for_code(code: str) -> V2StructuredLLMFailureKind:
    if code == "structured_llm_unavailable":
        return "configuration"
    if code in {
        "structured_llm_rate_limited",
        "structured_llm_provider_overloaded",
        "structured_llm_connection_failed",
        "structured_llm_timeout",
    }:
        return "provider_transient"
    if code.startswith("structured_output_"):
        return "content"
    return "provider_terminal"
