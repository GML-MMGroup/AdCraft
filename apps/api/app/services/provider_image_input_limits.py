"""Classify explicit upstream image input limits without retrying the request."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Literal


ImageInputLimitKind = Literal["reference_count", "image_size", "request_size"]


@dataclass(frozen=True)
class ProviderImageInputLimit:
    kind: ImageInputLimitKind
    provider_reason: str

    @property
    def message(self) -> str:
        label = {
            "reference_count": "reference image count",
            "image_size": "input image file size or dimensions",
            "request_size": "total request size",
        }[self.kind]
        reason = f" Provider reason: {self.provider_reason}" if self.provider_reason else ""
        return (
            f"The provider rejected the request because its {label} limit was exceeded. "
            "No further image compression or automatic retry will be performed. "
            "Reduce the reference count or replace oversized images before running again." + reason
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "input_limit_kind": self.kind,
            "retryable": False,
            "compression_retry_allowed": False,
        }


def classify_provider_image_input_limit(
    diagnostics: Mapping[str, Any], provider_message: str | None
) -> ProviderImageInputLimit | None:
    """Consume bounded, sanitized diagnostics; unknown failures remain unchanged."""
    if diagnostics.get("http_status") in {401, 402, 403, 429}:
        return None
    code = str(diagnostics.get("provider_error_code") or "").lower()
    if any(word in code for word in ("quota", "balance", "rate_limit", "ratelimit")):
        return None
    reason = provider_message or ""
    message = reason.lower()
    kind: ImageInputLimitKind | None = None
    if diagnostics.get("http_status") == 413 or code in {
        "payload_too_large",
        "request_too_large",
        "request_entity_too_large",
        "request_size_exceeded",
    }:
        kind = "request_size"
    elif code in {"too_many_images", "too_many_reference_images", "image_count_exceeded"}:
        kind = "reference_count"
    elif code in {"image_too_large", "image_size_exceeded", "input_image_too_large"}:
        kind = "image_size"
    elif re.search(
        r"too many (?:input |reference )?images\b|"
        r"(?:at most|maximum(?: of)?|up to|no more than) \d+ (?:input |reference )?images\b|"
        r"(?:number of (?:input |reference )?images|image count).*(?:exceed|maximum|limit)",
        message,
    ):
        kind = "reference_count"
    else:
        exceeded = re.search(r"exceed|too large|larger than|greater than|maximum|at most", message)
        if (
            exceeded
            and re.search(r"(?:input|reference|uploaded?) image|image file", message)
            and re.search(r"size|width|height|dimension|pixels|bytes|\b[mk]b\b", message)
        ):
            kind = "image_size"
        elif exceeded and re.search(r"(?:request|payload|body).*(?:size|bytes|large)", message):
            kind = "request_size"
    return ProviderImageInputLimit(kind, reason) if kind is not None else None
