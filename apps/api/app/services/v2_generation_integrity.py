from __future__ import annotations

from hashlib import sha256
import re
from typing import Any

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_integrity import (
    V2GenerationIntegrityAudit,
    V2PlanningConstraints,
    V2SlotSemanticContract,
)
from app.schemas.workflow_v2_planning import V2ExpertBriefPlan, V2ScriptPlan
from app.schemas.workflow_v2_style import (
    V2VisualStyleApplication,
    V2VisualStyleAudit,
    V2VisualStyleContract,
)
from app.services.v2_creative_inventory import creative_inventory_from_metadata
from app.services.v2_visual_style import V2VisualStyleContractError, V2VisualStyleService

V2_GENERATION_INTEGRITY_VERSION = "v2-generation-integrity-1"
V2_PLANNING_CONSTRAINTS_LOST = "v2_planning_constraints_lost"
V2_SLOT_SEMANTIC_BOUNDARY_FAILED = "v2_slot_semantic_boundary_failed"

_COUNT_WORDS = {
    "one": 1,
    "a": 1,
    "an": 1,
    "single": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


class V2GenerationIntegrityError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        audit: V2GenerationIntegrityAudit | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.audit = audit
        self.details = details or {}


class V2PlanningConstraintsExtractor:
    def extract(
        self,
        request: Any,
        *,
        normalized_request: dict[str, Any] | None = None,
        storyboard_config: dict[str, Any] | None = None,
    ) -> V2PlanningConstraints:
        metadata = dict(getattr(request, "metadata", {}) or {})
        creative_inventory = creative_inventory_from_metadata(metadata)
        prompt = " ".join(
            str(value or "")
            for value in (
                getattr(request, "prompt", ""),
                getattr(request, "product_name", ""),
                metadata.get("prompt"),
                (normalized_request or {}).get("prompt"),
            )
        )
        source_map: dict[str, str] = {}
        duration = _duration_seconds(request, prompt, normalized_request)
        aspect_ratio = str(getattr(request, "aspect_ratio", None) or "16:9")
        requested_shot_count = _first_int(
            getattr(request, "requested_shot_count", None),
            creative_inventory.storyboard_shot_count if creative_inventory else None,
            _metadata_int(metadata, "requested_shot_count"),
            _metadata_int(metadata, "shot_count"),
            _extract_count(prompt, ("storyboard shots", "shots", "shot")),
            _metadata_int(storyboard_config or {}, "requested_shot_count"),
            _metadata_int(storyboard_config or {}, "applied_shot_count"),
        )
        if requested_shot_count is not None:
            source_map["requested_shot_count"] = "request_or_prompt"
        requested_character_count = _first_int(
            len(creative_inventory.characters)
            if creative_inventory and creative_inventory.characters
            else None,
            _metadata_int(metadata, "requested_character_count"),
            _metadata_int(metadata, "character_count"),
            _extract_character_count(prompt),
        )
        if requested_character_count is not None:
            source_map["requested_character_count"] = "prompt"
        requested_scene_count = _first_int(
            len(creative_inventory.scenes)
            if creative_inventory and creative_inventory.scenes
            else None,
            _metadata_int(metadata, "requested_scene_count"),
            _metadata_int(metadata, "scene_count"),
            _extract_count(prompt, ("scenes", "scene")),
        )
        if requested_scene_count is not None:
            source_map["requested_scene_count"] = "prompt"
        requested_product_count = _first_int(
            len(creative_inventory.products)
            if creative_inventory and creative_inventory.products
            else None,
            _metadata_int(metadata, "requested_product_count"),
            _metadata_int(metadata, "product_count"),
            _extract_count(prompt, ("products", "product")),
        )
        if requested_product_count is None and (
            getattr(request, "product_name", None) or _looks_like_product_prompt(prompt)
        ):
            requested_product_count = 1
            source_map["requested_product_count"] = "product_name_or_prompt"
        requested_scene_styles = (
            _inventory_scene_styles(creative_inventory)
            if _creative_inventory_source(creative_inventory, "scenes") == "explicit_user_prompt"
            else []
        ) or _extract_scene_styles(prompt)
        if requested_scene_styles:
            source_map["requested_scene_styles"] = "prompt"
        return V2PlanningConstraints(
            requested_product_count=requested_product_count,
            requested_character_count=requested_character_count,
            requested_scene_count=requested_scene_count,
            requested_scene_styles=requested_scene_styles,
            requested_shot_count=requested_shot_count,
            duration_seconds=duration,
            aspect_ratio=aspect_ratio,
            source_map=source_map,
        )


class V2GenerationIntegrityService:
    def __init__(self) -> None:
        self._contracts = _contracts()
        self._visual_style = V2VisualStyleService()

    def validate_provider_style(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        media_type = payload.get("media_type")
        if media_type == "audio":
            return None
        try:
            contract = V2VisualStyleContract.model_validate(payload.get("visual_style_contract"))
            audit = V2VisualStyleAudit.model_validate(payload.get("visual_style_audit"))
        except (TypeError, ValueError) as exc:
            raise V2GenerationIntegrityError(
                "v2_visual_style_contract_failed",
                "Visual provider payload is missing a valid visual style contract.",
                details={
                    "stage": "visual_style_integrity",
                    "visual_style_audit": payload.get("visual_style_audit"),
                },
            ) from exc
        application = V2VisualStyleApplication(
            provider_prompt=str(payload.get("provider_prompt") or ""),
            negative_prompt=payload.get("negative_prompt"),
            negative_constraints=payload.get("negative_constraints"),
            contract=contract,
            audit=audit,
        )
        if (
            audit.contract_hash != contract.contract_hash()
            or audit.effective_source != contract.source
        ):
            raise V2GenerationIntegrityError(
                "v2_visual_style_contract_failed",
                "Visual style audit does not match the effective visual style contract.",
                details={
                    "stage": "visual_style_integrity",
                    "visual_style_audit": audit.model_dump(mode="json"),
                },
            )
        if payload.get("slot_type") == "final_video":
            return audit.model_dump(mode="json")
        try:
            self._visual_style.validate_application(application)
        except V2VisualStyleContractError as exc:
            raise V2GenerationIntegrityError(
                exc.code,
                str(exc),
                details={
                    "stage": exc.stage,
                    "visual_style_audit": exc.audit.model_dump(mode="json"),
                },
            ) from exc
        return audit.model_dump(mode="json")

    def contract_for_slot(self, slot_type: str) -> V2SlotSemanticContract:
        if slot_type.startswith("shot_cell_"):
            return self._contracts["shot_cell_*"]
        return self._contracts.get(slot_type) or V2SlotSemanticContract(
            slot_type=slot_type,
            allowed_subjects=["current slot prompt"],
            forbidden_subjects=[],
            allowed_reference_roles=[],
            composition_layer="asset",
        )

    def validate_slot(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_prompt: str,
        reference_asset_ids: list[str] | None = None,
    ) -> V2GenerationIntegrityAudit:
        contract = self.contract_for_slot(slot.slot_type)
        del reference_asset_ids
        detected = _forbidden_terms_for_slot(
            slot.slot_type,
            provider_prompt,
            item=item,
            workflow=workflow,
        )
        audit = _audit(
            slot_contract=contract.slot_type,
            provider_prompt=provider_prompt,
            semantic_boundary_passed=not detected,
            forbidden_terms_detected=detected,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            error_code=V2_SLOT_SEMANTIC_BOUNDARY_FAILED if detected else None,
            message=_boundary_message(slot.slot_type, detected) if detected else None,
            offending_reference_asset_ids=[],
        )
        if detected:
            raise V2GenerationIntegrityError(
                V2_SLOT_SEMANTIC_BOUNDARY_FAILED,
                audit.message,
                audit=audit,
                details=audit.model_dump(mode="json"),
            )
        return audit


def extract_planning_constraints(
    request: Any,
    *,
    normalized_request: dict[str, Any] | None = None,
    storyboard_config: dict[str, Any] | None = None,
) -> V2PlanningConstraints:
    return V2PlanningConstraintsExtractor().extract(
        request,
        normalized_request=normalized_request,
        storyboard_config=storyboard_config,
    )


def planning_constraints_from_metadata(
    metadata: dict[str, Any] | None,
) -> V2PlanningConstraints | None:
    raw = (metadata or {}).get("planning_constraints")
    if not isinstance(raw, dict):
        return None
    try:
        return V2PlanningConstraints.model_validate(raw)
    except Exception:
        return None


def _inventory_scene_styles(inventory: Any | None) -> list[str]:
    if inventory is None or not getattr(inventory, "scenes", None):
        return []
    return list(
        dict.fromkeys(
            str(scene.location_type).strip()
            for scene in inventory.scenes
            if str(scene.location_type).strip()
        )
    )


def _creative_inventory_source(inventory: Any | None, key: str) -> str | None:
    source_map = getattr(inventory, "source_map", None)
    if not isinstance(source_map, dict):
        return None
    entry = source_map.get(key)
    if not isinstance(entry, dict):
        return None
    source = entry.get("source")
    return str(source) if source is not None else None


def validate_script_plan_constraints(
    plan: V2ScriptPlan,
    constraints: V2PlanningConstraints | None,
) -> None:
    if constraints is None:
        return
    failures: list[dict[str, Any]] = []
    _expect_count(
        failures, "characters", constraints.requested_character_count, len(plan.characters)
    )
    _expect_count(failures, "scenes", constraints.requested_scene_count, len(plan.scenes))
    _expect_count(failures, "shots", constraints.requested_shot_count, len(plan.shots))
    if constraints.requested_scene_styles:
        text = _normalize(
            " ".join(
                [
                    plan.script_text,
                    plan.visual_style,
                    *[scene.title for scene in plan.scenes],
                    *[scene.description for scene in plan.scenes],
                    *[location.display_name for location in plan.locations],
                    *[location.description for location in plan.locations],
                    *[location.visual_notes for location in plan.locations],
                ]
            )
        )
        missing = [style for style in constraints.requested_scene_styles if style not in text]
        if missing:
            failures.append(
                {
                    "field": "scenes",
                    "expected_styles": constraints.requested_scene_styles,
                    "missing_styles": missing,
                }
            )
    if failures:
        raise V2GenerationIntegrityError(
            V2_PLANNING_CONSTRAINTS_LOST,
            "Script plan did not preserve explicit planning constraints.",
            details={"failures": failures},
        )


def validate_expert_brief_constraints(
    plan: V2ExpertBriefPlan,
    constraints: V2PlanningConstraints | None,
) -> None:
    if constraints is None:
        return
    failures: list[dict[str, Any]] = []
    _expect_count(
        failures, "products", constraints.requested_product_count, len(plan.product_briefs)
    )
    _expect_count(
        failures,
        "characters",
        constraints.requested_character_count,
        len(plan.character_briefs),
    )
    _expect_count(failures, "scenes", constraints.requested_scene_count, len(plan.scene_briefs))
    if constraints.requested_scene_styles:
        text = _normalize(
            " ".join(
                [
                    *[brief.display_name for brief in plan.scene_briefs],
                    *[brief.description for brief in plan.scene_briefs],
                    *[brief.item_prompt for brief in plan.scene_briefs],
                ]
            )
        )
        missing = [style for style in constraints.requested_scene_styles if style not in text]
        if missing:
            failures.append(
                {
                    "field": "scene_briefs",
                    "expected_styles": constraints.requested_scene_styles,
                    "missing_styles": missing,
                }
            )
    if failures:
        raise V2GenerationIntegrityError(
            V2_PLANNING_CONSTRAINTS_LOST,
            "Expert brief plan did not preserve explicit planning constraints.",
            details={"failures": failures},
        )


def _contracts() -> dict[str, V2SlotSemanticContract]:
    return {
        "product_main_image": V2SlotSemanticContract(
            slot_type="product_main_image",
            allowed_subjects=["single product reference"],
            forbidden_subjects=["people", "story action", "unrelated replacement product"],
            allowed_reference_roles=["product"],
            composition_layer="asset",
        ),
        "product_multi_view_grid": V2SlotSemanticContract(
            slot_type="product_multi_view_grid",
            allowed_subjects=["same product multi-view grid"],
            forbidden_subjects=["characters", "story action"],
            allowed_reference_roles=["product"],
            composition_layer="asset",
        ),
        "character_main_image": V2SlotSemanticContract(
            slot_type="character_main_image",
            allowed_subjects=["one reusable character"],
            forbidden_subjects=[
                "product use",
                "environment scene",
                "second character",
                "story action",
            ],
            allowed_reference_roles=["identity"],
            composition_layer="asset",
        ),
        "character_three_view": V2SlotSemanticContract(
            slot_type="character_three_view",
            allowed_subjects=["same character turnaround"],
            forbidden_subjects=["product use", "story scene", "unrelated character"],
            allowed_reference_roles=["identity"],
            composition_layer="asset",
        ),
        "scene_main_image": V2SlotSemanticContract(
            slot_type="scene_main_image",
            allowed_subjects=["environment reference"],
            forbidden_subjects=["foreground characters", "product interaction", "story beat"],
            allowed_reference_roles=["scene"],
            composition_layer="asset",
        ),
        "scene_multi_view_grid": V2SlotSemanticContract(
            slot_type="scene_multi_view_grid",
            allowed_subjects=["same environment multi-view grid"],
            forbidden_subjects=["characters", "product action"],
            allowed_reference_roles=["scene"],
            composition_layer="asset",
        ),
        "shot_cell_*": V2SlotSemanticContract(
            slot_type="shot_cell_*",
            allowed_subjects=[
                "product",
                "characters",
                "scene",
                "camera",
                "blocking",
                "story action",
            ],
            forbidden_subjects=[],
            allowed_reference_roles=["product", "character", "scene", "composition"],
            composition_layer="storyboard",
        ),
        "shot_video_segment": V2SlotSemanticContract(
            slot_type="shot_video_segment",
            allowed_subjects=["selected shot cells", "video motion prompt"],
            forbidden_subjects=[],
            allowed_reference_roles=["composition", "motion"],
            composition_layer="video",
        ),
        "bgm_audio": V2SlotSemanticContract(
            slot_type="bgm_audio",
            allowed_subjects=["instrumental music prompt"],
            forbidden_subjects=["image prompt", "video prompt"],
            allowed_reference_roles=["audio"],
            composition_layer="audio",
        ),
        "final_video": V2SlotSemanticContract(
            slot_type="final_video",
            allowed_subjects=["timeline assembly"],
            forbidden_subjects=["LLM media generation"],
            allowed_reference_roles=["composition", "audio"],
            composition_layer="timeline",
        ),
    }


def _forbidden_terms_for_slot(
    slot_type: str,
    provider_prompt: str,
    *,
    item: WorkflowItemV2,
    workflow: WorkflowV2,
) -> list[str]:
    text = _normalize(provider_prompt)
    detected: list[str] = []
    if slot_type in {"character_main_image", "character_three_view"}:
        detected.extend(
            _detect_phrases(
                text,
                (
                    "iphone",
                    "smartphone",
                    "holding",
                    "using product",
                    "product interaction",
                    "night street",
                    "urban street",
                    "walking",
                ),
            )
        )
    elif slot_type in {"scene_main_image", "scene_multi_view_grid"}:
        detected.extend(
            _detect_phrases(
                text,
                (
                    "lead man",
                    "lead woman",
                    "foreground character",
                    "foreground characters",
                    "people",
                    "person",
                    "man walks",
                    "woman walks",
                    "show the iphone",
                    "iphone on the desk",
                    "using iphone",
                    "holding iphone",
                    "person holding the product",
                    "product interaction",
                    "product placement",
                    "product showcase",
                    "product hero shot",
                    "story beat",
                    "blocking zone",
                    "blocking zones",
                ),
            )
        )
    elif slot_type in {"product_main_image", "product_multi_view_grid"}:
        detected.extend(
            _detect_phrases(
                text,
                (
                    "people",
                    "person",
                    "lead man",
                    "lead woman",
                    "holding",
                    "using",
                    "story action",
                    "street scene",
                ),
            )
        )
        product_text = _normalize(f"{workflow.prompt} {item.display_name} {item.description}")
        if "iphone" in product_text or "14 pro" in product_text:
            detected.extend(
                _detect_phrases(
                    text,
                    ("hand sanitizer", "milk", "detergent", "generic bottle", "bottle scene"),
                )
            )
    elif slot_type == "bgm_audio":
        detected.extend(_detect_phrases(text, ("image prompt", "video prompt", "storyboard cell")))
    elif slot_type == "final_video":
        detected.extend(_detect_phrases(text, ("generate a new video", "llm video generation")))
    return list(dict.fromkeys(detected))


def _audit(
    *,
    slot_contract: str,
    provider_prompt: str,
    semantic_boundary_passed: bool,
    forbidden_terms_detected: list[str],
    node_id: str,
    item_id: str,
    slot_id: str,
    slot_type: str,
    error_code: str | None,
    message: str | None,
    offending_reference_asset_ids: list[str],
) -> V2GenerationIntegrityAudit:
    prompt_hash = "sha256:" + sha256(provider_prompt.encode("utf-8")).hexdigest()
    return V2GenerationIntegrityAudit(
        slot_contract=slot_contract,
        semantic_boundary_passed=semantic_boundary_passed,
        forbidden_terms_removed=[],
        forbidden_terms_detected=forbidden_terms_detected,
        reference_scope="current_slot_only",
        source_prompt_hash=prompt_hash,
        validated_prompt_hash=prompt_hash,
        error_code=error_code,
        message=message,
        node_id=node_id,
        item_id=item_id,
        slot_id=slot_id,
        slot_type=slot_type,
        boundary_scope="scoped_provider_payload",
        offending_provider_prompt=provider_prompt if not semantic_boundary_passed else None,
        offending_reference_asset_ids=offending_reference_asset_ids,
    )


def _boundary_message(slot_type: str, detected: list[str]) -> str:
    return (
        f"{slot_type} violates reusable slot semantic boundary. "
        f"Detected forbidden terms: {', '.join(detected)}."
    )


def _detect_phrases(text: str, phrases: tuple[str, ...]) -> list[str]:
    detected: list[str] = []
    for phrase in phrases:
        start = text.find(phrase)
        while start >= 0:
            prefix = text[max(0, start - 40) : start]
            if not re.search(r"\b(no|without|avoid|exclude|not|never)\b", prefix):
                detected.append(phrase)
                break
            start = text.find(phrase, start + len(phrase))
    return detected


def _expect_count(
    failures: list[dict[str, Any]],
    field: str,
    expected: int | None,
    actual: int,
) -> None:
    if expected is None:
        return
    if actual != expected:
        failures.append({"field": field, "expected": expected, "actual": actual})


def _duration_seconds(
    request: Any,
    prompt: str,
    normalized_request: dict[str, Any] | None,
) -> int:
    for value in (
        getattr(request, "duration_seconds", None),
        (normalized_request or {}).get("duration_seconds"),
        _extract_duration(prompt),
    ):
        parsed = _coerce_int(value)
        if parsed is not None:
            return parsed
    return 30


def _extract_duration(prompt: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\s*[- ]?(?:second|sec|s)\b", prompt, flags=re.I)
    if match:
        return _coerce_int(match.group(1))
    return None


def _extract_character_count(prompt: str) -> int | None:
    text = _normalize(prompt)
    gender_count = 0
    for phrase in ("one man", "a man", "one male"):
        if phrase in text:
            gender_count += 1
            break
    for phrase in ("one woman", "a woman", "one female"):
        if phrase in text:
            gender_count += 1
            break
    if gender_count:
        return gender_count
    return _extract_count(prompt, ("characters", "character", "people"))


def _extract_scene_styles(prompt: str) -> list[str]:
    text = _normalize(prompt)
    ordered_styles = [
        "urban",
        "nature",
        "city",
        "street",
        "office",
        "home",
        "studio",
        "outdoor",
        "indoor",
        "beach",
        "forest",
    ]
    styles = [style for style in ordered_styles if re.search(rf"\b{style}\b", text)]
    if "city" in styles and "urban" in styles:
        styles.remove("city")
    return list(dict.fromkeys(styles))


def _extract_count(prompt: str, nouns: tuple[str, ...]) -> int | None:
    text = _normalize(prompt)
    noun_pattern = "|".join(re.escape(noun) for noun in nouns)
    count_pattern = r"\d{1,2}|" + "|".join(re.escape(word) for word in _COUNT_WORDS)
    for match in re.finditer(rf"\b({count_pattern})\s+(?:\w+\s+){{0,2}}({noun_pattern})\b", text):
        value = _coerce_count(match.group(1))
        if value is not None:
            return value
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _coerce_int(value)
        if parsed is not None:
            return parsed
    return None


def _metadata_int(metadata: dict[str, Any], key: str) -> int | None:
    return _coerce_int(metadata.get(key))


def _coerce_count(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if text in _COUNT_WORDS:
        return _COUNT_WORDS[text]
    return _coerce_int(text)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _looks_like_product_prompt(prompt: str) -> bool:
    text = _normalize(prompt)
    return any(term in text for term in ("product", "iphone", "phone", "ad", "commercial"))


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").split())
