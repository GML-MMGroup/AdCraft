from __future__ import annotations

from hashlib import sha256
import re
from typing import Literal

from pydantic import BaseModel, Field


V2_SPECIALIST_PROMPT_SANITIZER_VERSION = "v2-specialist-prompt-sanitizer-1"
SCENE_ASSET_ENVIRONMENT_ONLY_REASON = "scene_asset_must_be_environment_only"
NEGATIVE_PRODUCT_CONSTRAINT_REASON = "negative_product_constraint_normalized"
V2_SLOT_SEMANTIC_BOUNDARY_FAILED = "v2_slot_semantic_boundary_failed"


class V2PromptReplacement(BaseModel):
    from_text: str
    to_text: str
    reason: str


class V2PromptBoundaryViolation(BaseModel):
    code: str
    term: str
    polarity: Literal["positive", "negative", "unknown"]
    recoverable: bool


class V2PromptSanitizationResult(BaseModel):
    original_prompt_hash: str
    sanitized_prompt: str
    sanitized_prompt_hash: str
    replacements: list[V2PromptReplacement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unrecoverable_violations: list[V2PromptBoundaryViolation] = Field(default_factory=list)

    def audit(self) -> dict[str, object] | None:
        if not self.replacements and not self.warnings:
            return None
        return {
            "sanitized": bool(self.replacements),
            "replacements": [
                replacement.model_dump(mode="json") for replacement in self.replacements
            ],
            "warnings": list(self.warnings),
            "sanitizer_version": V2_SPECIALIST_PROMPT_SANITIZER_VERSION,
        }


class V2FallbackFieldCompletenessAudit(BaseModel):
    missing_required_fields: list[str] = Field(default_factory=list)
    defaults_applied: dict[str, str] = Field(default_factory=dict)
    invalid_fragments_removed: list[str] = Field(default_factory=list)
    sanitizer_version: str = V2_SPECIALIST_PROMPT_SANITIZER_VERSION

    def compact(self) -> dict[str, object] | None:
        if (
            not self.missing_required_fields
            and not self.defaults_applied
            and not self.invalid_fragments_removed
        ):
            return None
        return self.model_dump(mode="json")


class V2FallbackPromptCompletenessResult(BaseModel):
    prompt: str
    audit: V2FallbackFieldCompletenessAudit


class V2SpecialistPromptSanitizer:
    def sanitize_slot_prompt(
        self,
        *,
        slot_type: str,
        specialist_type: str,
        prompt: str | None,
    ) -> V2PromptSanitizationResult:
        del specialist_type
        original = str(prompt or "").strip()
        sanitized = original
        replacements: list[V2PromptReplacement] = []
        if slot_type in {"scene_main_image", "scene_multi_view_grid"}:
            sanitized, replacements = _apply_scene_replacements(sanitized)
        return V2PromptSanitizationResult(
            original_prompt_hash=_hash_prompt(original),
            sanitized_prompt=sanitized,
            sanitized_prompt_hash=_hash_prompt(sanitized),
            replacements=replacements,
        )

    def complete_fallback_prompt(
        self,
        *,
        slot_type: str,
        specialist_type: str,
        prompt: str | None,
        summary_prompt: str | None = None,
        visual_style_prompt: str | None = None,
    ) -> V2FallbackPromptCompletenessResult:
        original = str(prompt or "").strip()
        if specialist_type == "character_designer" and slot_type in {
            "character_main_image",
            "character_three_view",
        }:
            return _complete_character_prompt(
                original,
                summary_prompt=summary_prompt,
                visual_style_prompt=visual_style_prompt,
            )
        cleaned, invalid = _remove_invalid_fragments(original)
        return V2FallbackPromptCompletenessResult(
            prompt=cleaned,
            audit=V2FallbackFieldCompletenessAudit(invalid_fragments_removed=invalid),
        )


def _apply_scene_replacements(prompt: str) -> tuple[str, list[V2PromptReplacement]]:
    replacements: list[V2PromptReplacement] = []
    sanitized = prompt
    for from_text, to_text, reason in (
        (
            "ready for product placement",
            "clean foreground surface",
            SCENE_ASSET_ENVIRONMENT_ONLY_REASON,
        ),
        (
            "product display area",
            "empty foreground area",
            SCENE_ASSET_ENVIRONMENT_ONLY_REASON,
        ),
        (
            "hero product zone",
            "neutral foreground area",
            SCENE_ASSET_ENVIRONMENT_ONLY_REASON,
        ),
        (
            "no product placement",
            "no products, no product props, no product interaction",
            NEGATIVE_PRODUCT_CONSTRAINT_REASON,
        ),
    ):
        pattern = re.compile(rf"\b{re.escape(from_text)}\b", flags=re.IGNORECASE)
        if not pattern.search(sanitized):
            continue
        sanitized = pattern.sub(to_text, sanitized)
        replacements.append(
            V2PromptReplacement(from_text=from_text, to_text=to_text, reason=reason)
        )
    return _clean_spacing(sanitized), replacements


def _complete_character_prompt(
    prompt: str,
    *,
    summary_prompt: str | None,
    visual_style_prompt: str | None,
) -> V2FallbackPromptCompletenessResult:
    cleaned, invalid = _remove_invalid_fragments(prompt)
    missing: list[str] = []
    defaults: dict[str, str] = {}
    for field, default in _character_defaults(
        summary_prompt,
        visual_style_prompt=visual_style_prompt,
    ).items():
        value = _extract_field_value(cleaned, field)
        if value:
            continue
        missing.append(field)
        defaults[field] = default
    cleaned = _remove_empty_field_fragments(cleaned, fields=list(defaults))
    if defaults:
        default_clause = "; ".join(f"{field} {value}" for field, value in defaults.items())
        cleaned = f"{cleaned.rstrip(' .')}. Fallback character details: {default_clause}."
    return V2FallbackPromptCompletenessResult(
        prompt=_clean_spacing(cleaned),
        audit=V2FallbackFieldCompletenessAudit(
            missing_required_fields=missing,
            defaults_applied=defaults,
            invalid_fragments_removed=invalid,
        ),
    )


def _character_defaults(
    summary_prompt: str | None,
    *,
    visual_style_prompt: str | None,
) -> dict[str, str]:
    wardrobe = _derive_wardrobe(summary_prompt or "") or "neutral modern casual outfit"
    defaults = {
        "age impression": "adult commercial talent",
        "gender/person type": "single commercial character",
        "body type": "natural upright proportions",
        "wardrobe": wardrobe,
        "hair": "neat production-ready hairstyle",
        "facial features": "distinct approachable facial features",
        "expression": "calm confident expression",
        "pose": "neutral upright pose",
        "background": "plain neutral background",
    }
    if visual_style_prompt and visual_style_prompt.strip():
        defaults["visual style"] = visual_style_prompt.strip()
    return defaults


def _derive_wardrobe(text: str) -> str | None:
    match = re.search(
        r"\bwearing\s+([^.;,]{3,80})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        value = _clean_spacing(match.group(1))
        if _valid_field_value(value):
            return value
    return None


def _extract_field_value(prompt: str, field: str) -> str | None:
    if field == "gender/person type":
        if re.search(r"\b(man|woman|male|female|person|character|talent)\b", prompt, re.I):
            return "present"
        return None
    if field == "hair" and re.search(r"\bhairstyle\b\s*[:\-]?\s*[^.;,\n]{3,100}", prompt, re.I):
        return "present"
    pattern = re.compile(
        rf"\b{re.escape(field)}\b\s*[:\-]?\s*([^.;,\n]{{3,100}})",
        flags=re.IGNORECASE,
    )
    match = pattern.search(prompt)
    if not match:
        return None
    value = _clean_spacing(match.group(1))
    return value if _valid_field_value(value) else None


def _valid_field_value(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    return normalized not in {"undefined", "null", "none", "tbd", "placeholder"}


def _remove_invalid_fragments(prompt: str) -> tuple[str, list[str]]:
    removed: list[str] = []
    cleaned = prompt
    for fragment in ("undefined", "null", "TBD", "placeholder"):
        pattern = re.compile(rf"\b{re.escape(fragment)}\b", flags=re.IGNORECASE)
        if not pattern.search(cleaned):
            continue
        cleaned = pattern.sub("", cleaned)
        removed.append(fragment)
    return _clean_spacing(cleaned), removed


def _remove_empty_field_fragments(prompt: str, *, fields: list[str]) -> str:
    cleaned = prompt
    for field in fields:
        if field == "gender/person type":
            continue
        pattern = re.compile(
            rf"(^|[.;,])\s*{re.escape(field)}\s*[,;:]+",
            flags=re.IGNORECASE,
        )
        cleaned = pattern.sub(lambda match: match.group(1) + " ", cleaned)
    return _clean_spacing(cleaned)


def _clean_spacing(value: str) -> str:
    value = re.sub(r"\s+([,.;:])", r"\1", value)
    value = re.sub(r"([,.;:]){2,}", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+\.", ".", value)
    return value.strip(" ,;")


def _hash_prompt(prompt: str) -> str:
    return "sha256:" + sha256(prompt.encode("utf-8")).hexdigest()
