from __future__ import annotations

import re
from typing import Any

from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_expert_brief_contracts import (
    V2ExpertBriefQualityFailure,
    V2ExpertBriefQualityResult,
)
from app.schemas.workflow_v2_planning import (
    V2BgmBrief,
    V2ExpertBriefPlan,
    V2ScriptPlan,
)


class V2ExpertBriefQualityError(RuntimeError):
    def __init__(self, failures: list[V2ExpertBriefQualityFailure]) -> None:
        self.failures = failures
        self.failure_codes = [failure.code for failure in failures]
        self.code = failures[0].code if failures else "expert_brief_output_quality_failed"
        self.repair_details = _repair_details(failures)
        super().__init__("; ".join(f"{failure.code}: {failure.message}" for failure in failures))


class V2ExpertBriefQualityService:
    def validate_plan(
        self,
        plan: V2ExpertBriefPlan,
        *,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> V2ExpertBriefQualityResult:
        failures = self.evaluate_plan(plan, script_plan=script_plan, request=request)
        if failures:
            raise V2ExpertBriefQualityError(failures)
        return V2ExpertBriefQualityResult(passed=True, failures=[])

    def evaluate_plan(
        self,
        plan: V2ExpertBriefPlan,
        *,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> list[V2ExpertBriefQualityFailure]:
        failures: list[V2ExpertBriefQualityFailure] = []
        failures.extend(_coverage_failures(plan, script_plan))
        failures.extend(_source_mapping_failures(plan))
        failures.extend(_similarity_failures(plan))
        failures.extend(_role_failures(plan, request=request))
        failures.extend(_slot_prompt_failures(plan))
        failures.extend(_raw_wrapper_failures(plan, request=request, script_plan=script_plan))
        failures.extend(_payload_safety_failures(plan))
        return failures


def _coverage_failures(
    plan: V2ExpertBriefPlan,
    script_plan: V2ScriptPlan,
) -> list[V2ExpertBriefQualityFailure]:
    failures: list[V2ExpertBriefQualityFailure] = []
    expected_products = [
        str(item)
        for item in script_plan.metadata.get("creative_inventory_product_ids", ["product-1"])
        if str(item).strip()
    ]
    expected_characters = [character.character_id for character in script_plan.characters]
    expected_scenes = [location.location_id for location in script_plan.locations] or [
        scene.scene_id for scene in script_plan.scenes
    ]
    failures.extend(
        _brief_id_coverage_failures(
            category="product",
            expected_ids=expected_products,
            actual_ids=[brief.item_id for brief in plan.product_briefs],
        )
    )
    failures.extend(
        _brief_id_coverage_failures(
            category="character",
            expected_ids=expected_characters,
            actual_ids=[brief.item_id for brief in plan.character_briefs],
        )
    )
    failures.extend(
        _brief_id_coverage_failures(
            category="scene",
            expected_ids=expected_scenes,
            actual_ids=[brief.item_id for brief in plan.scene_briefs],
        )
    )
    return failures


def _brief_id_coverage_failures(
    *,
    category: str,
    expected_ids: list[str],
    actual_ids: list[str],
) -> list[V2ExpertBriefQualityFailure]:
    failures: list[V2ExpertBriefQualityFailure] = []
    duplicate_ids = sorted({item for item in actual_ids if actual_ids.count(item) > 1})
    if duplicate_ids:
        failures.append(
            _failure(
                f"expert_brief_duplicate_{category}_id",
                f"{category.title()} brief IDs must be unique.",
                evidence=f"duplicate_ids={duplicate_ids}",
            )
        )
    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    extra_ids = sorted(set(actual_ids) - set(expected_ids))
    if missing_ids or extra_ids or len(actual_ids) != len(expected_ids):
        failures.append(
            _failure(
                f"expert_brief_missing_{category}",
                f"{category.title()} briefs must exactly cover authoritative IDs.",
                evidence=(
                    f"expected_ids={expected_ids} actual_ids={actual_ids} "
                    f"missing_ids={missing_ids} extra_ids={extra_ids}"
                ),
            )
        )
    return failures


def _source_mapping_failures(plan: V2ExpertBriefPlan) -> list[V2ExpertBriefQualityFailure]:
    failures: list[V2ExpertBriefQualityFailure] = []
    for brief in [
        *plan.product_briefs,
        *plan.character_briefs,
        *plan.scene_briefs,
        plan.bgm_brief,
    ]:
        if not brief.source_scene_ids or not brief.source_shot_ids:
            failures.append(
                _failure(
                    "expert_brief_source_mapping_missing",
                    "Expert brief is missing source scene or shot mapping.",
                    item_id=brief.item_id,
                )
            )
    return failures


def _similarity_failures(plan: V2ExpertBriefPlan) -> list[V2ExpertBriefQualityFailure]:
    prompts = {
        brief.item_id: _normalize_text(brief.item_prompt)
        for brief in [
            *plan.product_briefs,
            *plan.character_briefs,
            *plan.scene_briefs,
            plan.bgm_brief,
        ]
    }
    failures: list[V2ExpertBriefQualityFailure] = []
    keys = sorted(prompts)
    for index, left_key in enumerate(keys):
        for right_key in keys[index + 1 :]:
            if _token_similarity(prompts[left_key], prompts[right_key]) >= 0.88:
                failures.append(
                    _failure(
                        "expert_brief_prompts_too_similar",
                        "Expert brief prompts are too similar across distinct roles.",
                        item_id=f"{left_key}:{right_key}",
                    )
                )
    return failures


def _role_failures(
    plan: V2ExpertBriefPlan,
    *,
    request: WorkflowV2PlanFromPromptRequest,
) -> list[V2ExpertBriefQualityFailure]:
    failures: list[V2ExpertBriefQualityFailure] = []
    for brief in plan.product_briefs:
        text = _role_text(brief.item_prompt, brief.slot_prompts)
        if not _all_terms(
            text, ("product identity", "silhouette", "selling", "usage", "visual style")
        ):
            failures.append(
                _failure(
                    "expert_brief_role_contamination",
                    "Product brief is missing product identity and selling-point language.",
                    item_id=brief.item_id,
                )
            )
        if _contains_any(text, ("wardrobe", "emotion arc", "music", "storyboard camera")):
            failures.append(
                _failure(
                    "expert_brief_role_contamination",
                    "Product brief includes another role's design language.",
                    item_id=brief.item_id,
                )
            )
    for brief in plan.character_briefs:
        text = _role_text(brief.item_prompt, brief.slot_prompts)
        if not _all_terms(
            text, ("identity", "wardrobe", "silhouette", "performance role", "emotion arc")
        ):
            failures.append(
                _failure(
                    "expert_brief_role_contamination",
                    "Character brief is missing character identity and performance language.",
                    item_id=brief.item_id,
                )
            )
        main_prompt = brief.slot_prompts.get("character_main_image", "")
        if _has_positive_forbidden_term(
            main_prompt,
            (
                "three-view",
                "three view",
                "turnaround",
                "multi-view",
                "grid",
                "sheet",
                "contact sheet",
                "collage",
                "scene layout",
                "music",
            ),
        ):
            failures.append(
                _failure(
                    "expert_brief_role_contamination",
                    "Character main image prompt requests a layout or non-character role.",
                    item_id=brief.item_id,
                    slot_type="character_main_image",
                )
            )
    for brief in plan.scene_briefs:
        text = _role_text(brief.item_prompt, brief.slot_prompts)
        if not _all_terms(
            text, ("spatial layout", "lighting", "materials", "time of day", "blocking")
        ):
            failures.append(
                _failure(
                    "expert_brief_role_contamination",
                    "Scene brief is missing location layout and blocking language.",
                    item_id=brief.item_id,
                )
            )
        main_prompt = brief.slot_prompts.get("scene_main_image", "")
        if _has_positive_forbidden_term(
            main_prompt,
            ("character sheet", "product-only hero", "storyboard panels", "video timing", "music"),
        ):
            failures.append(
                _failure(
                    "expert_brief_role_contamination",
                    "Scene main prompt includes another role's output type.",
                    item_id=brief.item_id,
                    slot_type="scene_main_image",
                )
            )
    failures.extend(_bgm_role_failures(plan.bgm_brief, request=request))
    return failures


def _bgm_role_failures(
    brief: V2BgmBrief,
    *,
    request: WorkflowV2PlanFromPromptRequest,
) -> list[V2ExpertBriefQualityFailure]:
    del request
    text = _role_text(brief.item_prompt, brief.slot_prompts)
    required = ("instrumental", "pace", "energy", "duration", "no vocals", "no lyrics")
    if not _all_terms(text, required):
        return [
            _failure(
                "expert_brief_role_contamination",
                "BGM brief is missing instrumental music constraints.",
                item_id=brief.item_id,
            )
        ]
    forbidden = ("image prompt", "scene layout", "storyboard", "video generation")
    if _contains_any(text, forbidden):
        return [
            _failure(
                "expert_brief_role_contamination",
                "BGM brief contains non-audio generation instructions.",
                item_id=brief.item_id,
            )
        ]
    return []


def _slot_prompt_failures(plan: V2ExpertBriefPlan) -> list[V2ExpertBriefQualityFailure]:
    expected = {
        "product": ("product_main_image", "product_multi_view_grid"),
        "character": ("character_main_image", "character_three_view"),
        "scene": ("scene_main_image", "scene_multi_view_grid"),
        "bgm": ("bgm_audio",),
    }
    failures: list[V2ExpertBriefQualityFailure] = []
    for kind, briefs in (
        ("product", plan.product_briefs),
        ("character", plan.character_briefs),
        ("scene", plan.scene_briefs),
        ("bgm", [plan.bgm_brief]),
    ):
        for brief in briefs:
            missing = [
                slot_type
                for slot_type in expected[kind]
                if not brief.slot_prompts.get(slot_type, "").strip()
            ]
            if missing:
                failures.append(
                    _failure(
                        "expert_brief_slot_prompt_missing",
                        "Expert brief is missing required slot prompts.",
                        item_id=brief.item_id,
                        evidence=", ".join(missing),
                    )
                )
    return failures


def _raw_wrapper_failures(
    plan: V2ExpertBriefPlan,
    *,
    request: WorkflowV2PlanFromPromptRequest,
    script_plan: V2ScriptPlan,
) -> list[V2ExpertBriefQualityFailure]:
    source_texts = {_normalize_text(request.prompt), _normalize_text(script_plan.script_title)}
    wrappers = ("product brief for", "character brief:", "scene brief:", "bgm brief:")
    failures: list[V2ExpertBriefQualityFailure] = []
    for brief in [*plan.product_briefs, *plan.character_briefs, *plan.scene_briefs, plan.bgm_brief]:
        normalized = _normalize_text(brief.item_prompt)
        if any(normalized.startswith(wrapper) for wrapper in wrappers):
            remaining = normalized.split(" ", 3)[-1] if " " in normalized else normalized
            if remaining in source_texts or len(remaining.split()) < 12:
                failures.append(
                    _failure(
                        "expert_brief_raw_prompt_wrapper",
                        "Expert brief is a shallow wrapper instead of a role-specific handoff.",
                        item_id=brief.item_id,
                    )
                )
    return failures


def _payload_safety_failures(plan: V2ExpertBriefPlan) -> list[V2ExpertBriefQualityFailure]:
    payload = plan.model_dump(mode="json")
    unsafe = list(_unsafe_payload_paths(payload))
    if not unsafe:
        return []
    return [
        _failure(
            "expert_brief_payload_unsafe",
            "Expert brief payload contains raw media, data URLs, oversized content, or secrets.",
            evidence=", ".join(unsafe[:8]),
        )
    ]


def _failure(
    code: str,
    message: str,
    *,
    item_id: str | None = None,
    slot_type: str | None = None,
    evidence: str | None = None,
) -> V2ExpertBriefQualityFailure:
    return V2ExpertBriefQualityFailure(
        code=code,
        message=message,
        item_id=item_id,
        slot_type=slot_type,
        evidence=evidence,
    )


def _repair_details(failures: list[V2ExpertBriefQualityFailure]) -> dict[str, Any]:
    missing_slot_prompts: list[dict[str, str]] = []
    missing_terms: list[dict[str, Any]] = []
    seen_terms: set[tuple[str, str, str]] = set()
    for failure in failures:
        brief_type = _brief_type_for_failure(failure)
        if failure.code == "expert_brief_slot_prompt_missing":
            for slot_type in _missing_slot_types(failure):
                missing_slot_prompts.append(
                    {
                        "brief_type": brief_type,
                        "item_id": failure.item_id or "",
                        "slot_type": slot_type,
                    }
                )
            term_entry = _missing_terms_entry(brief_type, failure.item_id)
            key = (term_entry["brief_type"], term_entry["item_id"], term_entry["field"])
            if key not in seen_terms:
                missing_terms.append(term_entry)
                seen_terms.add(key)
            continue
        if failure.code == "expert_brief_role_contamination":
            term_entry = _missing_terms_entry(brief_type, failure.item_id)
            key = (term_entry["brief_type"], term_entry["item_id"], term_entry["field"])
            if key not in seen_terms:
                missing_terms.append(term_entry)
                seen_terms.add(key)
    return {
        "failures": [failure.model_dump(mode="json") for failure in failures],
        "missing_slot_prompts": missing_slot_prompts,
        "missing_terms": missing_terms,
    }


def _missing_slot_types(failure: V2ExpertBriefQualityFailure) -> list[str]:
    if failure.slot_type:
        return [failure.slot_type]
    if not failure.evidence:
        return []
    return [value.strip() for value in failure.evidence.split(",") if value.strip()]


def _brief_type_for_item_id(item_id: str | None) -> str:
    if not item_id:
        return "unknown"
    if item_id.startswith("product-"):
        return "product"
    if item_id.startswith("character-"):
        return "character"
    if item_id.startswith("scene-"):
        return "scene"
    if item_id.startswith("bgm-"):
        return "bgm"
    return "unknown"


def _brief_type_for_failure(failure: V2ExpertBriefQualityFailure) -> str:
    slot_types = _missing_slot_types(failure)
    slot_type = failure.slot_type or (slot_types[0] if slot_types else "")
    if slot_type.startswith("product_"):
        return "product"
    if slot_type.startswith("character_"):
        return "character"
    if slot_type.startswith("scene_"):
        return "scene"
    if slot_type == "bgm_audio":
        return "bgm"
    return _brief_type_for_item_id(failure.item_id)


def _missing_terms_entry(brief_type: str, item_id: str | None) -> dict[str, Any]:
    required_terms = {
        "product": [
            "product identity",
            "recognizable silhouette",
            "selling points",
            "usage context",
            "visual style",
        ],
        "character": [
            "identity",
            "wardrobe",
            "silhouette",
            "performance role",
            "emotion arc",
        ],
        "scene": [
            "spatial layout",
            "lighting",
            "materials",
            "time of day",
            "blocking",
        ],
        "bgm": [
            "instrumental",
            "pace",
            "energy",
            "duration",
            "no vocals",
            "no lyrics",
        ],
    }.get(brief_type, [])
    return {
        "brief_type": brief_type,
        "item_id": item_id or "",
        "field": "item_prompt",
        "required_terms": required_terms,
    }


def _role_text(item_prompt: str, slot_prompts: dict[str, str]) -> str:
    return " ".join([item_prompt, *slot_prompts.values()]).lower()


def _all_terms(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return all(term in normalized for term in terms)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in terms)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower())).strip()


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _has_positive_forbidden_term(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    for term in terms:
        start = normalized.find(term)
        while start >= 0:
            prefix = normalized[max(0, start - 24) : start]
            if not re.search(r"\b(no|without|avoid|exclude|not|never)\b", prefix):
                return True
            start = normalized.find(term, start + len(term))
    return False


def _unsafe_payload_paths(value: Any, *, prefix: str = "$") -> list[str]:
    unsafe: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}"
            if any(
                sensitive in key_text
                for sensitive in (
                    "api_key",
                    "apikey",
                    "secret",
                    "token",
                    "password",
                    "raw_bytes",
                    "file_content",
                    "base64",
                    "data_url",
                )
            ):
                unsafe.append(path)
                continue
            unsafe.extend(_unsafe_payload_paths(item, prefix=path))
        return unsafe
    if isinstance(value, list):
        for index, item in enumerate(value):
            unsafe.extend(_unsafe_payload_paths(item, prefix=f"{prefix}[{index}]"))
        return unsafe
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized.startswith("data:") or "base64," in normalized or len(value) > 20_000:
            unsafe.append(prefix)
    return unsafe
