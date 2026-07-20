from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator


VisualStyleSource = Literal[
    "explicit_user",
    "inferred",
    "slot_user_override",
    "selected_reference",
    "system_default",
]


class V2VisualStyleContract(BaseModel):
    contract_version: Literal["v2-visual-style-1"] = "v2-visual-style-1"
    rendering_medium: str = Field(min_length=1, max_length=120)
    style_prompt: str = Field(min_length=1, max_length=1_000)
    negative_constraints: list[str] = Field(default_factory=list, max_length=20)
    source: VisualStyleSource
    source_text: str | None = Field(default=None, max_length=500)
    is_user_explicit: bool = False

    @field_validator("rendering_medium", "style_prompt", "source_text", mode="after")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("visual style text must not be empty")
        return normalized

    @field_validator("negative_constraints", mode="after")
    @classmethod
    def normalize_negative_constraints(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                continue
            if len(text) > 500:
                raise ValueError("visual style negative constraint must be at most 500 characters")
            key = text.casefold()
            if key not in seen:
                normalized.append(text)
                seen.add(key)
        return normalized

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "rendering_medium": self.rendering_medium,
            "style_prompt": self.style_prompt,
            "negative_constraints": self.negative_constraints,
            "source": self.source,
            "source_text": self.source_text,
            "is_user_explicit": self.is_user_explicit,
        }

    def contract_hash(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class V2VisualStyleAudit(BaseModel):
    contract_hash: str
    effective_source: VisualStyleSource
    positive_clause_added: bool = False
    removed_negative_fragments: list[str] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    reference_style_preserved: bool = False


class V2VisualStyleApplication(BaseModel):
    provider_prompt: str
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    contract: V2VisualStyleContract
    audit: V2VisualStyleAudit
