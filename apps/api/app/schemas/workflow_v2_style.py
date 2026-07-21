from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


VisualStyleScopeStatus = Literal["valid", "repaired"]
VisualStyleScopeRepairMode = Literal[
    "none",
    "structured_repair",
    "deterministic_fallback",
]
VisualStyleScopeSource = Literal[
    "planning",
    "run_preflight",
    "slot_generate",
    "slot_regenerate",
]


class V2VisualStyleScopeAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_version: Literal["v2-visual-style-scope-1"] = "v2-visual-style-scope-1"
    status: VisualStyleScopeStatus
    repair_mode: VisualStyleScopeRepairMode
    source: VisualStyleScopeSource
    removed_scopes: list[Literal["product_identity"]] = Field(default_factory=list, max_length=1)
    original_contract_hash: str = Field(min_length=8, max_length=80)
    effective_contract_hash: str = Field(min_length=8, max_length=80)
    extracted_constraint_count: int = Field(ge=0, le=10)
    structured_repair_error_code: str | None = Field(default=None, max_length=120)

    @field_validator("structured_repair_error_code", mode="after")
    @classmethod
    def normalize_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized) is None:
            raise ValueError("structured repair error code must be a bounded identifier")
        return normalized


class V2VisualStyleResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: V2VisualStyleContract
    product_identity_constraints: list[str] = Field(default_factory=list, max_length=10)
    audit: V2VisualStyleScopeAudit

    @field_validator("product_identity_constraints", mode="after")
    @classmethod
    def normalize_product_constraints(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                continue
            if len(text) > 500:
                raise ValueError("product identity constraint must be at most 500 characters")
            key = text.casefold()
            if key not in seen:
                normalized.append(text)
                seen.add(key)
        return normalized


class V2VisualStyleScopeRepairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rendering_style: str = Field(min_length=1, max_length=1_000)
    product_identity_constraints: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("rendering_style", mode="after")
    @classmethod
    def normalize_rendering_style(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("rendering style must not be empty")
        return normalized

    @field_validator("product_identity_constraints", mode="after")
    @classmethod
    def normalize_constraints(cls, value: list[str]) -> list[str]:
        return V2VisualStyleResolution.normalize_product_constraints(value)
