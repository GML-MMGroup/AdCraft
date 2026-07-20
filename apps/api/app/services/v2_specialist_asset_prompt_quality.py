from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.workflow_v2_planning import V2ExpertBriefPlan

SpecialistType = Literal["product", "character", "scene"]

SPECIALIST_ASSET_PROMPT_QUALITY_FAILED = "specialist_asset_prompt_quality_failed"
SPECIALIST_ASSET_PROMPT_CONTAMINATION_REJECTED = "specialist_asset_prompt_contamination_rejected"
SPECIALIST_ASSET_PROMPT_QUALITY_STAGE = "specialist_asset_prompt_quality"


class V2SpecialistQualityViolation(BaseModel):
    code: str
    stage: str = SPECIALIST_ASSET_PROMPT_QUALITY_STAGE
    specialist_type: SpecialistType
    item_id: str
    slot_type: str
    message: str
    repair_instruction: str
    evidence: str | None = None


class V2SpecialistQualityAudit(BaseModel):
    status: Literal["passed", "repaired", "fallback_used", "failed"] = "passed"
    repair_used: bool = False
    fallback_used: bool = False
    violations: list[V2SpecialistQualityViolation] = Field(default_factory=list)


class V2SpecialistAssetPromptQualityError(RuntimeError):
    def __init__(self, violations: list[V2SpecialistQualityViolation]) -> None:
        self.violations = violations
        self.code = violations[0].code if violations else SPECIALIST_ASSET_PROMPT_QUALITY_FAILED
        self.repair_details = _repair_details(violations)
        message = "; ".join(f"{violation.code}: {violation.message}" for violation in violations)
        super().__init__(message or SPECIALIST_ASSET_PROMPT_QUALITY_FAILED)


class V2SpecialistAssetPromptQualityValidator:
    def validate_plan(self, plan: V2ExpertBriefPlan, **kwargs: Any) -> V2SpecialistQualityAudit:
        del kwargs
        violations = self.evaluate_plan(plan)
        if violations:
            raise V2SpecialistAssetPromptQualityError(violations)
        return V2SpecialistQualityAudit()

    def evaluate_plan(self, plan: V2ExpertBriefPlan) -> list[V2SpecialistQualityViolation]:
        violations: list[V2SpecialistQualityViolation] = []
        for brief in plan.product_briefs:
            violations.extend(
                self.evaluate_asset_prompts(
                    specialist_type="product",
                    item_id=brief.item_id,
                    asset_prompts=_asset_prompts_for_brief(brief),
                    required_slot_types=("product_main_image", "product_multi_view_grid"),
                )
            )
        for brief in plan.character_briefs:
            violations.extend(
                self.evaluate_asset_prompts(
                    specialist_type="character",
                    item_id=brief.item_id,
                    asset_prompts=_asset_prompts_for_brief(brief),
                    required_slot_types=("character_main_image", "character_three_view"),
                )
            )
        for brief in plan.scene_briefs:
            violations.extend(
                self.evaluate_asset_prompts(
                    specialist_type="scene",
                    item_id=brief.item_id,
                    asset_prompts=_asset_prompts_for_brief(brief),
                    required_slot_types=("scene_main_image", "scene_multi_view_grid"),
                )
            )
        return violations

    def validate_asset_prompt(
        self,
        *,
        specialist_type: SpecialistType,
        item_id: str,
        slot_type: str,
        prompt: str,
    ) -> V2SpecialistQualityAudit:
        violations = self.evaluate_asset_prompt(
            specialist_type=specialist_type,
            item_id=item_id,
            slot_type=slot_type,
            prompt=prompt,
        )
        if violations:
            raise V2SpecialistAssetPromptQualityError(violations)
        return V2SpecialistQualityAudit()

    def evaluate_asset_prompts(
        self,
        *,
        specialist_type: SpecialistType,
        item_id: str,
        asset_prompts: dict[str, str],
        required_slot_types: tuple[str, ...],
    ) -> list[V2SpecialistQualityViolation]:
        violations: list[V2SpecialistQualityViolation] = []
        for slot_type in required_slot_types:
            prompt = str(asset_prompts.get(slot_type) or "").strip()
            violations.extend(
                self.evaluate_asset_prompt(
                    specialist_type=specialist_type,
                    item_id=item_id,
                    slot_type=slot_type,
                    prompt=prompt,
                )
            )
        return violations

    def evaluate_asset_prompt(
        self,
        *,
        specialist_type: SpecialistType,
        item_id: str,
        slot_type: str,
        prompt: str,
    ) -> list[V2SpecialistQualityViolation]:
        if not prompt.strip():
            return [
                self.violation(
                    specialist_type=specialist_type,
                    item_id=item_id,
                    slot_type=slot_type,
                    code=SPECIALIST_ASSET_PROMPT_QUALITY_FAILED,
                    message=f"{slot_type} asset prompt is required.",
                    repair_instruction=_repair_instruction(specialist_type),
                )
            ]
        violations: list[V2SpecialistQualityViolation] = []
        if _is_shallow_wrapper(prompt):
            violations.append(
                self.violation(
                    specialist_type=specialist_type,
                    item_id=item_id,
                    slot_type=slot_type,
                    message="Asset prompt uses a shallow raw-prompt wrapper.",
                    repair_instruction=_repair_instruction(specialist_type),
                    evidence="raw_prompt_wrapper",
                )
            )
        detected = _detected_contamination(specialist_type, prompt)
        if detected:
            violations.append(
                self.violation(
                    specialist_type=specialist_type,
                    item_id=item_id,
                    slot_type=slot_type,
                    message=_message(specialist_type, detected),
                    repair_instruction=_repair_instruction(specialist_type),
                    evidence=", ".join(detected),
                )
            )
        return violations

    def violation(
        self,
        *,
        specialist_type: SpecialistType,
        item_id: str,
        slot_type: str,
        message: str,
        repair_instruction: str,
        code: str = SPECIALIST_ASSET_PROMPT_CONTAMINATION_REJECTED,
        evidence: str | None = None,
    ) -> V2SpecialistQualityViolation:
        return V2SpecialistQualityViolation(
            code=code,
            specialist_type=specialist_type,
            item_id=item_id,
            slot_type=slot_type,
            message=message,
            repair_instruction=repair_instruction,
            evidence=evidence,
        )


def specialist_quality_audit(
    *,
    status: Literal["passed", "repaired", "fallback_used", "failed"] = "passed",
    repair_used: bool = False,
    fallback_used: bool = False,
    violations: list[V2SpecialistQualityViolation] | None = None,
) -> dict[str, Any]:
    return V2SpecialistQualityAudit(
        status=status,
        repair_used=repair_used,
        fallback_used=fallback_used,
        violations=violations or [],
    ).model_dump(mode="json")


def _asset_prompts_for_brief(brief: Any) -> dict[str, str]:
    prompts: dict[str, str] = {}
    asset_prompts = getattr(brief, "asset_prompts", None)
    if isinstance(asset_prompts, dict):
        prompts.update(
            {str(key): str(value) for key, value in asset_prompts.items() if str(value).strip()}
        )
    slot_prompts = getattr(brief, "slot_prompts", None)
    if isinstance(slot_prompts, dict):
        prompts.update(
            {str(key): str(value) for key, value in slot_prompts.items() if str(value).strip()}
        )
    return prompts


def _detected_contamination(specialist_type: SpecialistType, prompt: str) -> list[str]:
    terms = {
        "product": (
            "actor",
            "actors",
            "human performance",
            "people",
            "person",
            "man",
            "woman",
            "street scene",
            "story scene",
            "lifestyle story",
            "story action",
            "action beat",
            "milk",
            "sanitizer",
            "detergent",
            "generic bottle",
            "unrelated bottle",
            "unrelated product",
            "holding",
            "using",
        ),
        "character": (
            "iphone",
            "smartphone",
            "product usage",
            "using the product",
            "holding the product",
            "holding iphone",
            "using iphone",
            "shooting video with",
            "city street",
            "street scene",
            "rooftop scene",
            "kitchen scene",
            "environment scene",
            "other characters",
            "second character",
            "story action",
            "action beat",
            "storyboard blocking",
            "blocking",
        ),
        "scene": (
            "foreground character",
            "foreground characters",
            "characters",
            "people",
            "person",
            "actor",
            "actors",
            "cast member",
            "cast members",
            "man",
            "woman",
            "iphone",
            "smartphone",
            "product handling",
            "product action",
            "product interaction",
            "using product",
            "holding product",
            "holding iphone",
            "using iphone",
            "story action",
            "storyboard action",
            "storyboard beat",
            "action beat",
            "blocking",
        ),
    }[specialist_type]
    return _positive_terms(prompt, terms)


def _positive_terms(prompt: str, terms: tuple[str, ...]) -> list[str]:
    normalized = _normalize(prompt)
    detected: list[str] = []
    for term in terms:
        start = normalized.find(term)
        while start >= 0:
            prefix = normalized[max(0, start - 32) : start]
            if not re.search(r"\b(no|without|avoid|exclude|not|never|plain)\b", prefix):
                detected.append(term)
                break
            start = normalized.find(term, start + len(term))
    return list(dict.fromkeys(detected))


def _is_shallow_wrapper(prompt: str) -> bool:
    normalized = _normalize(prompt)
    return any(
        normalized.startswith(wrapper)
        for wrapper in (
            "professional prompt for",
            "product image prompt",
            "character image prompt",
            "character design prompt",
            "scene image prompt",
            "scene design prompt",
        )
    )


def _message(specialist_type: SpecialistType, detected: list[str]) -> str:
    return (
        f"{specialist_type.title()} asset prompt contains forbidden cross-layer context: "
        f"{', '.join(detected)}."
    )


def _repair_instruction(specialist_type: SpecialistType) -> str:
    if specialist_type == "product":
        return (
            "Product asset prompts must describe only product identity, silhouette, material, "
            "color, label or screen constraints, and product-only view requirements."
        )
    if specialist_type == "character":
        return (
            "Character asset prompts must describe only reusable character references: one "
            "character identity, age range, body type, face, hairstyle, wardrobe, expression, "
            "and clean neutral presentation."
        )
    return (
        "Scene asset prompts must describe only reusable environment references: spatial "
        "layout, architecture, props, lighting, materials, color palette, time of day, and "
        "camera-neutral atmosphere."
    )


def _repair_details(violations: list[V2SpecialistQualityViolation]) -> dict[str, Any]:
    serialized = [violation.model_dump(mode="json") for violation in violations]
    return {
        "stage": SPECIALIST_ASSET_PROMPT_QUALITY_STAGE,
        "specialist_quality_violations": serialized,
        "failures": serialized,
    }


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("-", " ")).strip()
