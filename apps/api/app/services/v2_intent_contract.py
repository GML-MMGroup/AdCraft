from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
import re
from typing import Any
import unicodedata

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_intent import (
    V2FrontDeskPlanningSeed,
    V2_MAX_INTENT_INVENTORY_ITEMS,
    V2ExplicitCharacterConstraint,
    V2ExplicitConstraints,
    V2ExplicitSceneConstraint,
    V2IntentAudio,
    V2IntentCharacter,
    V2IntentPlan,
    V2IntentProduct,
    V2IntentScene,
    V2IntentStoryboard,
    V2IntentValidationResult,
    V2IntentValidationViolation,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_structured_generation_runtime import (
    QualityValidationError,
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)
from app.services.v2_planning_seed import (
    canonicalize_v2_planning_seed,
    merge_v2_planning_seed_constraints,
)
from app.services.v2_structured_llm import V2StructuredLLMClient, V2StructuredLLMError
from app.services.v2_storyboard_planning import (
    V2_MAX_SHOT_DURATION_SECONDS,
    V2_MAX_STORYBOARD_SHOT_COUNT,
    V2_MAX_TOTAL_DURATION_SECONDS,
    V2_MIN_SHOT_DURATION_SECONDS,
)


_ENGLISH_COUNTS = {
    "one": 1,
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


class V2IntentPlannerError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class V2IntentPlanningOutcome:
    intent_plan: V2IntentPlan
    intent_validation: V2IntentValidationResult
    explicit_constraints: V2ExplicitConstraints
    intent_repair_used: bool = False
    intent_fallback_used: bool = False
    warnings: list[dict[str, Any]] = field(default_factory=list)
    trace_metadata: dict[str, Any] = field(default_factory=dict)


class ExplicitConstraintScanner:
    """Safety-belt scanner for hard explicit constraints; not a creative planner."""

    def scan(
        self,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        normalized_request: dict[str, Any] | None = None,
    ) -> V2ExplicitConstraints:
        text = _combined_text(request, normalized_request)
        canonical = _canonical_explicit_constraints(normalized_request)
        product_name, product_span = _product_identity(request, text)
        characters = canonical.characters or _explicit_characters(text)
        scenes = canonical.scenes or _explicit_scenes(text)
        scene_count, _scene_count_span = _aggregate_scene_count(text)
        shot_count, shot_span = _explicit_storyboard_shot_count(text)
        duration, duration_span = _explicit_duration(text)
        return V2ExplicitConstraints(
            product_name=canonical.product_name or product_name,
            product_source_span=canonical.product_source_span or product_span,
            character_count=canonical.character_count
            if canonical.character_count is not None
            else (len(characters) or None),
            characters=characters,
            scenes=scenes,
            scene_count=canonical.scene_count
            if canonical.scene_count is not None
            else (max(scene_count or 0, len(scenes) if len(scenes) > 1 else 0) or None),
            storyboard_shot_count=canonical.storyboard_shot_count
            or shot_count
            or request.requested_shot_count,
            storyboard_shot_count_span=canonical.storyboard_shot_count_span or shot_span,
            duration_seconds=canonical.duration_seconds or duration or request.duration_seconds,
            duration_source_span=canonical.duration_source_span or duration_span,
            aspect_ratio=request.aspect_ratio,
        )


class V2IntentPlanner:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        validator: "V2IntentValidator | None" = None,
        repairer: "V2IntentRepairer | None" = None,
        fallback_builder: "V2IntentFallbackBuilder | None" = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._validator = validator or V2IntentValidator()
        self._repairer = repairer or V2IntentRepairer()
        self._fallback_builder = fallback_builder or V2IntentFallbackBuilder()
        self._structured_runtime = StructuredGenerationRuntime(
            settings=self._settings,
            structured_llm=V2StructuredLLMClient(self._settings),
        )

    def plan(
        self,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        normalized_request: dict[str, Any] | None,
        explicit_constraints: V2ExplicitConstraints,
        workflow_id_seed: str | None = None,
        planning_seed: V2FrontDeskPlanningSeed | None = None,
    ) -> V2IntentPlanningOutcome:
        seed_warnings: list[dict[str, str]] = []
        if planning_seed is not None:
            canonicalization = canonicalize_v2_planning_seed(planning_seed, request)
            planning_seed = canonicalization.seed
            seed_warnings = canonicalization.warnings
            explicit_constraints = merge_v2_planning_seed_constraints(
                explicit_constraints,
                planning_seed,
            )
        _raise_if_intent_clarification_required(request, explicit_constraints)
        if self._settings.agno_mock_mode:
            intent = self._deterministic_plan(request, explicit_constraints, planning_seed)
            return self._validate_repair_or_fallback(
                intent,
                request=request,
                normalized_request=normalized_request,
                explicit_constraints=explicit_constraints,
                planning_seed=planning_seed,
                initial_warnings=seed_warnings,
            )

        spec = StructuredGenerationSpec[V2IntentPlan](
            stage_name="intent_contract_planner",
            contract_name="V2IntentPlan",
            model_id=self._settings.llm_creative_model,
            system_prompt=_intent_planner_system_prompt(),
            input_payload=_intent_planner_payload(
                request=request,
                normalized_request=normalized_request,
                explicit_constraints=explicit_constraints,
            ),
            output_model=V2IntentPlan,
            quality_validator=lambda intent: self._raise_if_invalid(
                intent,
                request=request,
                normalized_request=normalized_request,
                explicit_constraints=explicit_constraints,
            ),
            repair_context_builder=_intent_repair_context,
            fallback_builder=lambda error: self._fallback_builder.apply(
                request,
                explicit_constraints=explicit_constraints,
                planning_seed=planning_seed,
                original_error=error,
            ),
            trace_metadata={"workflow_id": workflow_id_seed or ""},
            temperature=0.2,
        )
        try:
            result = self._structured_runtime.run(spec)
        except StructuredGenerationRuntimeError as exc:
            raise V2IntentPlannerError(
                _runtime_error_code(exc),
                str(exc),
                details={
                    "planning_id": workflow_id_seed,
                    "attempts": [attempt.model_dump(mode="json") for attempt in exc.attempts],
                    "trace_metadata": sanitize_context_for_llm_text(exc.trace_metadata),
                },
            ) from exc

        return self._validate_repair_or_fallback(
            result.output,
            request=request,
            normalized_request=normalized_request,
            explicit_constraints=explicit_constraints,
            planning_seed=planning_seed,
            initial_warnings=[*seed_warnings, *result.warnings],
            repair_used=result.mode == "repair",
            fallback_used=result.mode == "fallback",
            trace_metadata=result.trace_metadata,
        )

    def _deterministic_plan(
        self,
        request: WorkflowV2PlanFromPromptRequest,
        explicit_constraints: V2ExplicitConstraints,
        planning_seed: V2FrontDeskPlanningSeed | None,
    ) -> V2IntentPlan:
        return self._fallback_builder.apply(
            request,
            explicit_constraints=explicit_constraints,
            planning_seed=planning_seed,
        )

    def _raise_if_invalid(
        self,
        intent: V2IntentPlan,
        *,
        request: WorkflowV2PlanFromPromptRequest,
        normalized_request: dict[str, Any] | None,
        explicit_constraints: V2ExplicitConstraints,
    ) -> None:
        validation = self._validator.validate(
            intent,
            explicit_constraints=explicit_constraints,
            original_prompt=request.prompt,
            normalized_request=normalized_request,
        )
        if not validation.valid:
            raise QualityValidationError(
                "v2_intent_validation_failed",
                "Intent plan did not preserve explicit constraints.",
                details={"violations": [v.model_dump(mode="json") for v in validation.violations]},
            )

    def _validate_repair_or_fallback(
        self,
        intent: V2IntentPlan,
        *,
        request: WorkflowV2PlanFromPromptRequest,
        normalized_request: dict[str, Any] | None,
        explicit_constraints: V2ExplicitConstraints,
        planning_seed: V2FrontDeskPlanningSeed | None,
        initial_warnings: list[dict[str, Any]],
        repair_used: bool = False,
        fallback_used: bool = False,
        trace_metadata: dict[str, Any] | None = None,
    ) -> V2IntentPlanningOutcome:
        validation = self._validator.validate(
            intent,
            explicit_constraints=explicit_constraints,
            original_prompt=request.prompt,
            normalized_request=normalized_request,
        )
        if not validation.valid:
            try:
                intent = self._repairer.repair(
                    intent,
                    validation.violations,
                    explicit_constraints=explicit_constraints,
                    request=request,
                    normalized_request=normalized_request,
                )
                repair_used = True
            except Exception:
                intent = self._fallback_builder.apply(
                    request,
                    explicit_constraints=explicit_constraints,
                    planning_seed=planning_seed,
                )
                fallback_used = True
            validation = self._validator.validate(
                intent,
                explicit_constraints=explicit_constraints,
                original_prompt=request.prompt,
                normalized_request=normalized_request,
            )
            if not validation.valid and not fallback_used:
                intent = self._fallback_builder.apply(
                    request,
                    explicit_constraints=explicit_constraints,
                    planning_seed=planning_seed,
                )
                fallback_used = True
                validation = self._validator.validate(
                    intent,
                    explicit_constraints=explicit_constraints,
                    original_prompt=request.prompt,
                    normalized_request=normalized_request,
                )
        if not validation.valid:
            raise V2IntentPlannerError(
                "v2_intent_validation_failed",
                "Intent validation failed after repair/fallback.",
                details={"violations": [v.model_dump(mode="json") for v in validation.violations]},
            )
        return V2IntentPlanningOutcome(
            intent_plan=intent,
            intent_validation=validation,
            explicit_constraints=explicit_constraints,
            intent_repair_used=repair_used,
            intent_fallback_used=fallback_used,
            warnings=initial_warnings,
            trace_metadata=trace_metadata or {},
        )


class V2IntentValidator:
    def validate(
        self,
        intent_plan: V2IntentPlan,
        *,
        explicit_constraints: V2ExplicitConstraints,
        original_prompt: str,
        normalized_request: dict[str, Any] | None,
        script_plan: Any | None = None,
        expert_brief_plan: Any | None = None,
    ) -> V2IntentValidationResult:
        violations: list[V2IntentValidationViolation] = []
        validation_text = _validation_text(original_prompt, normalized_request)
        for path, fact in _iter_intent_facts(intent_plan):
            if fact.source == "explicit" and not fact.source_span:
                violations.append(
                    _violation(
                        "missing_explicit_source_span",
                        "Explicit intent fact is missing source_span.",
                        field_path=path,
                    )
                )
            if (
                fact.source == "explicit"
                and fact.source_span
                and fact.source_span not in validation_text
            ):
                violations.append(
                    _violation(
                        "explicit_source_span_not_found",
                        "Explicit source_span was not found in the request text.",
                        source_span=fact.source_span,
                        field_path=path,
                    )
                )

        for category, items, id_field in (
            ("product", intent_plan.products, "product_id"),
            ("character", intent_plan.characters, "character_id"),
            ("scene", intent_plan.scenes, "scene_id"),
        ):
            if len(items) > V2_MAX_INTENT_INVENTORY_ITEMS:
                violations.append(
                    _violation(
                        f"{category}_count_out_of_bounds",
                        f"Intent {category} count exceeds the configured V2 limit.",
                        field_path=f"{category}s",
                        expected=V2_MAX_INTENT_INVENTORY_ITEMS,
                        actual=len(items),
                    )
                )
            seen_ids: set[str] = set()
            for index, item in enumerate(items):
                item_id = str(getattr(item, id_field))
                if item_id in seen_ids:
                    violations.append(
                        _violation(
                            f"duplicate_{category}_id",
                            f"Intent contains a duplicate {category} ID.",
                            field_path=f"{category}s[{index}].{id_field}",
                            actual=item_id,
                        )
                    )
                seen_ids.add(item_id)

        if explicit_constraints.character_count is not None and (
            len(intent_plan.characters) != explicit_constraints.character_count
        ):
            violations.append(
                _violation(
                    "character_count_mismatch",
                    "Intent character count does not match explicit request.",
                    expected=explicit_constraints.character_count,
                    actual=len(intent_plan.characters),
                )
            )

        expected_genders = [item.gender for item in explicit_constraints.characters if item.gender]
        if expected_genders:
            actual_genders = [item.gender for item in intent_plan.characters if item.gender]
            missing = list(expected_genders)
            for gender in actual_genders:
                if gender in missing:
                    missing.remove(gender)
            if missing:
                violations.append(
                    _violation(
                        "character_gender_mismatch",
                        "Intent character genders do not match explicit request.",
                        expected=expected_genders,
                        actual=actual_genders,
                    )
                )

        if explicit_constraints.scene_count is not None and (
            len(intent_plan.scenes) != explicit_constraints.scene_count
        ):
            violations.append(
                _violation(
                    "scene_count_mismatch",
                    "Intent scene count does not match explicit request.",
                    expected=explicit_constraints.scene_count,
                    actual=len(intent_plan.scenes),
                )
            )
        actual_scene_kinds = {scene.kind for scene in intent_plan.scenes}
        for scene in explicit_constraints.scenes:
            if scene.kind not in actual_scene_kinds:
                violations.append(
                    _violation(
                        "missing_explicit_scene",
                        "Intent omitted an explicitly requested scene kind.",
                        expected_kind=scene.kind,
                        source_span=scene.source_span,
                    )
                )

        if explicit_constraints.storyboard_shot_count is not None and (
            intent_plan.storyboard.shot_count != explicit_constraints.storyboard_shot_count
        ):
            violations.append(
                _violation(
                    "shot_count_mismatch",
                    "Intent storyboard shot count does not match explicit request.",
                    expected=explicit_constraints.storyboard_shot_count,
                    actual=intent_plan.storyboard.shot_count,
                    source_span=explicit_constraints.storyboard_shot_count_span,
                )
            )

        if script_plan is not None:
            scene_count = len(getattr(script_plan, "scenes", []) or [])
            shot_count = len(getattr(script_plan, "shots", []) or [])
            if (
                scene_count != len(intent_plan.scenes)
                or shot_count != intent_plan.storyboard.shot_count
            ):
                violations.append(
                    _violation(
                        "script_intent_count_mismatch",
                        "Script plan counts drifted from validated intent.",
                        expected={
                            "scenes": len(intent_plan.scenes),
                            "shots": intent_plan.storyboard.shot_count,
                        },
                        actual={"scenes": scene_count, "shots": shot_count},
                    )
                )
            expected_product_ids = {item.product_id for item in intent_plan.products}
            expected_character_ids = {item.character_id for item in intent_plan.characters}
            expected_scene_ids = {item.scene_id for item in intent_plan.scenes}
            actual_product_ids = set(
                str(item)
                for item in (getattr(script_plan, "metadata", {}) or {}).get(
                    "creative_inventory_product_ids", []
                )
            )
            actual_character_ids = {
                item.character_id for item in (getattr(script_plan, "characters", []) or [])
            }
            actual_scene_ids = {
                item.scene_id for item in (getattr(script_plan, "scenes", []) or [])
            }
            for category, expected_ids, actual_ids in (
                ("product", expected_product_ids, actual_product_ids),
                ("character", expected_character_ids, actual_character_ids),
                ("scene", expected_scene_ids, actual_scene_ids),
            ):
                if expected_ids != actual_ids:
                    violations.append(
                        _violation(
                            f"script_{category}_id_set_mismatch",
                            f"Script {category} IDs do not match authoritative intent IDs.",
                            expected=sorted(expected_ids),
                            actual=sorted(actual_ids),
                        )
                    )

            shots = list(getattr(script_plan, "shots", []) or [])
            used_ids = {
                "product": {item for shot in shots for item in shot.product_ids},
                "character": {item for shot in shots for item in shot.character_ids},
                "scene": {item for shot in shots for item in shot.scene_ids},
            }
            missing_usage = {
                category: sorted(expected_ids - used_ids[category])
                for category, expected_ids in (
                    ("product", expected_product_ids),
                    ("character", expected_character_ids),
                    ("scene", expected_scene_ids),
                )
                if expected_ids - used_ids[category]
            }
            if missing_usage:
                violations.append(
                    _violation(
                        "script_inventory_usage_missing",
                        "Script shots do not use every authoritative inventory item.",
                        expected=missing_usage,
                    )
                )

            script_characters = {
                item.character_id: item for item in (getattr(script_plan, "characters", []) or [])
            }
            for character in intent_plan.characters:
                script_character = script_characters.get(character.character_id)
                if (
                    script_character is not None
                    and character.gender
                    and getattr(script_character, "gender", None) != character.gender
                ):
                    violations.append(
                        _violation(
                            "script_character_attribute_mismatch",
                            "Script character attributes do not match authoritative intent.",
                            field_path=f"characters.{character.character_id}.gender",
                            expected=character.gender,
                            actual=getattr(script_character, "gender", None),
                        )
                    )

            script_scenes = {
                item.scene_id: item for item in (getattr(script_plan, "scenes", []) or [])
            }
            for scene in intent_plan.scenes:
                script_scene = script_scenes.get(scene.scene_id)
                if script_scene is None:
                    continue
                expected_attributes = {
                    "time_of_day": scene.time_of_day,
                    "setting_type": scene.setting_type,
                }
                mismatched = {
                    key: {"expected": value, "actual": getattr(script_scene, key, None)}
                    for key, value in expected_attributes.items()
                    if value is not None and getattr(script_scene, key, None) != value
                }
                if mismatched:
                    violations.append(
                        _violation(
                            "script_scene_attribute_mismatch",
                            "Script scene attributes do not match authoritative intent.",
                            field_path=f"scenes.{scene.scene_id}",
                            expected=mismatched,
                        )
                    )

        if expert_brief_plan is not None:
            actual = {
                "products": len(getattr(expert_brief_plan, "product_briefs", []) or []),
                "characters": len(getattr(expert_brief_plan, "character_briefs", []) or []),
                "scenes": len(getattr(expert_brief_plan, "scene_briefs", []) or []),
            }
            expected = {
                "products": len(intent_plan.products),
                "characters": len(intent_plan.characters),
                "scenes": len(intent_plan.scenes),
            }
            if actual != expected:
                violations.append(
                    _violation(
                        "expert_brief_intent_count_mismatch",
                        "Expert brief counts drifted from validated intent.",
                        expected=expected,
                        actual=actual,
                    )
                )
            expected_ids = {
                "product": {item.product_id for item in intent_plan.products},
                "character": {item.character_id for item in intent_plan.characters},
                "scene": {item.scene_id for item in intent_plan.scenes},
            }
            actual_ids = {
                "product": {item.item_id for item in expert_brief_plan.product_briefs},
                "character": {item.item_id for item in expert_brief_plan.character_briefs},
                "scene": {item.item_id for item in expert_brief_plan.scene_briefs},
            }
            for category in ("product", "character", "scene"):
                if expected_ids[category] != actual_ids[category]:
                    violations.append(
                        _violation(
                            f"expert_brief_{category}_id_set_mismatch",
                            f"Expert brief {category} IDs do not match authoritative intent IDs.",
                            expected=sorted(expected_ids[category]),
                            actual=sorted(actual_ids[category]),
                        )
                    )

        return V2IntentValidationResult(valid=not violations, violations=violations)


class V2IntentRepairer:
    def repair(
        self,
        invalid_intent: V2IntentPlan,
        violations: list[V2IntentValidationViolation],
        *,
        explicit_constraints: V2ExplicitConstraints,
        request: WorkflowV2PlanFromPromptRequest,
        normalized_request: dict[str, Any] | None,
    ) -> V2IntentPlan:
        del normalized_request
        products = _products_from_constraints(request, explicit_constraints)
        characters = _characters_from_constraints(explicit_constraints) or list(
            invalid_intent.characters
        )
        scenes = list(invalid_intent.scenes)
        scene_kinds = {scene.kind for scene in scenes}
        for constraint in explicit_constraints.scenes:
            if constraint.kind not in scene_kinds:
                scenes.append(_intent_scene_from_constraint(constraint, len(scenes) + 1))
                scene_kinds.add(constraint.kind)
        if explicit_constraints.scenes and any(
            violation.code in {"scene_count_mismatch", "missing_explicit_scene"}
            for violation in violations
        ):
            scenes = [
                _intent_scene_from_constraint(scene, index)
                for index, scene in enumerate(explicit_constraints.scenes, start=1)
            ]

        storyboard = invalid_intent.storyboard
        if explicit_constraints.storyboard_shot_count is not None:
            storyboard = V2IntentStoryboard(
                shot_count=explicit_constraints.storyboard_shot_count,
                source="explicit"
                if explicit_constraints.storyboard_shot_count_span
                else "inferred",
                source_span=explicit_constraints.storyboard_shot_count_span,
                confidence=0.96,
                reason="Repaired storyboard shot count from explicit constraints.",
            )

        return invalid_intent.model_copy(
            update={
                "products": products or invalid_intent.products,
                "characters": characters,
                "scenes": scenes,
                "storyboard": storyboard,
                "warnings": [
                    *invalid_intent.warnings,
                    {
                        "code": "v2_intent_repair_used",
                        "violations": [
                            violation.model_dump(mode="json") for violation in violations
                        ],
                    },
                ],
            },
            deep=True,
        )


class V2IntentFallbackBuilder:
    def apply(
        self,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        explicit_constraints: V2ExplicitConstraints,
        planning_seed: V2FrontDeskPlanningSeed | None = None,
        original_error: V2StructuredLLMError | None = None,
    ) -> V2IntentPlan:
        _raise_if_intent_clarification_required(request, explicit_constraints)
        if planning_seed is None and _requires_structured_semantic_normalization(
            request,
            explicit_constraints,
        ):
            raise V2IntentPlannerError(
                "v2_intent_fallback_failed",
                "Structured semantic normalization is required for multilingual planning.",
            )
        products = _products_from_constraints(request, explicit_constraints)
        if not products:
            raise V2IntentPlannerError(
                "v2_intent_clarification_required",
                "Product identity is required before creating a V2 workflow.",
                details={"missing": ["product_name"]},
            )
        concept_mode = _fallback_concept_mode(request)
        characters = _characters_from_constraints(explicit_constraints)
        if not characters and explicit_constraints.character_count != 0:
            characters = _default_characters(concept_mode)
        storyboard = _storyboard_from_constraints(request, explicit_constraints)
        explicit_scenes = [
            _intent_scene_from_constraint(scene, index)
            for index, scene in enumerate(explicit_constraints.scenes, start=1)
        ]
        scene_count = explicit_constraints.scene_count
        if explicit_scenes:
            target_scene_count = scene_count or len(explicit_scenes)
            scenes = [
                *explicit_scenes,
                *_default_scenes(
                    target_scene_count - len(explicit_scenes),
                    start_index=len(explicit_scenes) + 1,
                ),
            ]
        else:
            scenes = _default_scenes(scene_count or 2)
        audio = V2IntentAudio(
            audio_mode=request.audio_mode,
            source="default",
            source_span=None,
            confidence=0.75,
            reason="Audio mode comes from the V2 planning request.",
        )
        warnings: list[dict[str, Any]] = []
        if original_error is not None:
            warnings.append(
                {
                    "code": "v2_intent_fallback_used",
                    "original_error_code": original_error.code,
                }
            )
        return V2IntentPlan(
            concept_mode=concept_mode,
            products=products,
            characters=characters,
            scenes=scenes,
            storyboard=storyboard,
            audio=audio,
            warnings=warnings,
        )


def _raise_if_intent_clarification_required(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
) -> None:
    if not (explicit_constraints.product_name or request.product_name):
        raise V2IntentPlannerError(
            "v2_intent_clarification_required",
            "Product identity is required before creating a V2 workflow.",
            details={"missing": ["product_name"]},
        )
    if (
        explicit_constraints.scene_count is not None
        and len(explicit_constraints.scenes) > explicit_constraints.scene_count
    ):
        raise V2IntentPlannerError(
            "v2_intent_clarification_required",
            "Explicit scene constraints are mutually impossible.",
            details={
                "reason": "scene_constraints_conflict",
                "requested_scene_count": explicit_constraints.scene_count,
                "explicit_scene_count": len(explicit_constraints.scenes),
                "explicit_scene_kinds": [scene.kind for scene in explicit_constraints.scenes],
            },
        )
    duration_seconds = explicit_constraints.duration_seconds or request.duration_seconds
    if duration_seconds > V2_MAX_TOTAL_DURATION_SECONDS:
        raise V2IntentPlannerError(
            "v2_intent_clarification_required",
            "Requested video duration exceeds V2 storyboard limits.",
            details={
                "reason": "video_duration_not_supported",
                "requested_duration_seconds": duration_seconds,
                "max_total_duration_seconds": V2_MAX_TOTAL_DURATION_SECONDS,
            },
        )
    shot_count = explicit_constraints.storyboard_shot_count or request.requested_shot_count
    if shot_count is None:
        return
    if shot_count < 1 or shot_count > V2_MAX_STORYBOARD_SHOT_COUNT:
        raise V2IntentPlannerError(
            "v2_intent_clarification_required",
            "Requested storyboard shot count exceeds V2 limits.",
            details={
                "reason": "storyboard_shot_count_not_supported",
                "requested_duration_seconds": duration_seconds,
                "requested_shot_count": shot_count,
                "max_storyboard_shot_count": V2_MAX_STORYBOARD_SHOT_COUNT,
            },
        )
    duration_per_shot = duration_seconds / shot_count
    if duration_per_shot > V2_MAX_SHOT_DURATION_SECONDS:
        raise V2IntentPlannerError(
            "v2_intent_clarification_required",
            "Requested storyboard shot duration exceeds V2 provider limits.",
            details={
                "reason": "storyboard_shot_duration_not_supported",
                "requested_duration_seconds": duration_seconds,
                "requested_shot_count": shot_count,
                "max_shot_duration_seconds": V2_MAX_SHOT_DURATION_SECONDS,
                "suggested_min_shot_count": ceil(duration_seconds / V2_MAX_SHOT_DURATION_SECONDS),
            },
        )
    if duration_per_shot < V2_MIN_SHOT_DURATION_SECONDS:
        raise V2IntentPlannerError(
            "v2_intent_clarification_required",
            "Requested storyboard shot count creates segments that are too short.",
            details={
                "reason": "storyboard_shot_count_not_supported",
                "requested_duration_seconds": duration_seconds,
                "requested_shot_count": shot_count,
                "min_shot_duration_seconds": V2_MIN_SHOT_DURATION_SECONDS,
            },
        )


def _combined_text(
    request: WorkflowV2PlanFromPromptRequest,
    normalized_request: dict[str, Any] | None,
) -> str:
    metadata = request.metadata or {}
    parts = [
        request.prompt,
        metadata.get("prompt"),
        _flatten_text(normalized_request or {}),
    ]
    return " ".join(str(part or "") for part in parts).strip()


def _canonical_explicit_constraints(
    normalized_request: dict[str, Any] | None,
) -> V2ExplicitConstraints:
    raw = normalized_request or {}
    nested = raw.get("explicit_constraints")
    payload = nested if isinstance(nested, dict) else raw

    raw_characters = payload.get("characters")
    characters: list[V2ExplicitCharacterConstraint] = []
    if isinstance(raw_characters, list):
        for item in raw_characters:
            if not isinstance(item, dict):
                continue
            gender = _optional_text(item.get("gender"), lowercase=True)
            source_span = _optional_text(item.get("source_span"))
            if gender or source_span:
                characters.append(
                    V2ExplicitCharacterConstraint(
                        gender=gender,
                        source_span=source_span,
                    )
                )

    raw_scenes = payload.get("scenes")
    scenes: list[V2ExplicitSceneConstraint] = []
    if isinstance(raw_scenes, list):
        for item in raw_scenes:
            if not isinstance(item, dict):
                continue
            kind = _optional_text(item.get("kind"), lowercase=True)
            source_span = _optional_text(item.get("source_span"))
            if not kind or not source_span:
                continue
            scenes.append(
                V2ExplicitSceneConstraint(
                    kind=kind,
                    source_span=source_span,
                    time_of_day=_optional_text(item.get("time_of_day"), lowercase=True),
                    setting_type=_optional_text(item.get("setting_type"), lowercase=True),
                )
            )

    return V2ExplicitConstraints(
        product_name=_optional_text(payload.get("product_name")),
        product_source_span=_optional_text(payload.get("product_source_span")),
        character_count=_non_negative_integer(payload.get("character_count"))
        if payload.get("character_count") is not None
        else (len(raw_characters) if isinstance(raw_characters, list) else None),
        characters=characters,
        scenes=scenes,
        scene_count=_positive_integer(payload.get("scene_count"))
        or (len(raw_scenes) if isinstance(raw_scenes, list) and raw_scenes else None),
        storyboard_shot_count=_positive_integer(payload.get("storyboard_shot_count")),
        storyboard_shot_count_span=_optional_text(payload.get("storyboard_shot_count_span")),
        duration_seconds=_positive_integer(payload.get("duration_seconds")),
        duration_source_span=_optional_text(payload.get("duration_source_span")),
        aspect_ratio=_optional_text(payload.get("aspect_ratio")),
    )


def _optional_text(value: Any, *, lowercase: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text.lower() if lowercase else text


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _non_negative_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _requires_structured_semantic_normalization(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
) -> bool:
    if not any(
        ord(character) > 127 and unicodedata.category(character).startswith("L")
        for character in request.prompt
    ):
        return False
    return any(
        value is None
        for value in (
            explicit_constraints.character_count,
            explicit_constraints.scene_count,
            explicit_constraints.storyboard_shot_count,
        )
    )


def _validation_text(
    original_prompt: str,
    normalized_request: dict[str, Any] | None,
) -> str:
    return " ".join([original_prompt or "", _flatten_text(normalized_request or {})]).strip()


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _product_identity(
    request: WorkflowV2PlanFromPromptRequest,
    text: str,
) -> tuple[str | None, str | None]:
    if request.product_name:
        span = _find_span(text, request.product_name)
        return request.product_name, span
    iphone = _match_span(text, r"\biPhone\s*\d{1,2}(?:\s*Pro(?:\s*Max)?)?\b")
    if iphone:
        return iphone, iphone
    named_match = re.search(
        r"\b(?:for|advertise|ad for|launch ad for)\s+"
        r"([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,4})\b",
        text,
    )
    if named_match:
        named = named_match.group(1).strip()
        return named, named
    return None, None


def _explicit_characters(text: str) -> list[V2ExplicitCharacterConstraint]:
    span = _match_span(
        text,
        (
            r"\b(one male and one female(?:\s+character[s]?)?|one man and one woman|"
            r"one male character and one female character)\b"
        ),
    )
    if span:
        return [
            V2ExplicitCharacterConstraint(gender="male", source_span=span),
            V2ExplicitCharacterConstraint(gender="female", source_span=span),
        ]
    count, span = _aggregate_character_count(text)
    if count is None:
        return []
    return [V2ExplicitCharacterConstraint(source_span=span) for _ in range(count)]


def _explicit_scenes(text: str) -> list[V2ExplicitSceneConstraint]:
    scenes: list[V2ExplicitSceneConstraint] = []
    detailed_patterns = (
        (
            "office",
            (r"\b(?:daytime\s+)?office(?:\s+(?:interior|indoors?))?\b",),
        ),
        (
            "night_street",
            (
                r"\b(?:(?:(?!(?:a|an|the|one|two|three)\b)"
                r"[A-Za-z][A-Za-z-]*\s+)?night(?:time)?\s+"
                r"(?:city\s+)?street(?:\s+(?:scene|exterior))?|"
                r"(?:city\s+)?street\s+(?:at\s+night(?:time)?|exterior)"
                r"(?:\s+as\s+an?\s+exterior(?:\s+location)?)?)\b",
            ),
        ),
    )
    for kind, patterns in detailed_patterns:
        for pattern in patterns:
            span = _match_span(text, pattern)
            if not span:
                continue
            scenes.append(
                V2ExplicitSceneConstraint(
                    kind=kind,
                    source_span=span,
                    time_of_day=_scene_time_of_day(span),
                    setting_type=_scene_setting_type(span),
                )
            )
            break

    detailed_kinds = {scene.kind for scene in scenes}
    detailed_spans = [scene.source_span.lower() for scene in scenes]
    for kind, patterns in (
        ("office", (r"\boffice scene\b", r"\boffice\b")),
        ("urban", (r"\burban style\b", r"\burban scene\b", r"\burban\b")),
        ("nature", (r"\bnature style\b", r"\bnature scene\b", r"\bnature\b")),
        (
            "night_street",
            (
                r"\bnight street scene\b",
                r"\bnight street\b",
            ),
        ),
    ):
        if kind in detailed_kinds:
            continue
        for pattern in patterns:
            span = _match_span(text, pattern)
            if span:
                if any(span.lower() in detailed_span for detailed_span in detailed_spans):
                    break
                scenes.append(V2ExplicitSceneConstraint(kind=kind, source_span=span))
                break
    return scenes


def _aggregate_character_count(text: str) -> tuple[int | None, str | None]:
    english = re.search(
        r"\b(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+characters?\b",
        text,
        flags=re.IGNORECASE,
    )
    if english:
        raw_count = english.group("count").lower()
        count = _ENGLISH_COUNTS.get(raw_count, int(raw_count) if raw_count.isdigit() else None)
        return count, english.group(0)
    return None, None


def _scene_time_of_day(span: str) -> str | None:
    lowered = span.lower()
    if "daytime" in lowered:
        return "daytime"
    if "night" in lowered:
        return "night"
    return None


def _scene_setting_type(span: str) -> str | None:
    lowered = span.lower()
    if "interior" in lowered or "indoor" in lowered:
        return "interior"
    if "exterior" in lowered or "outdoor" in lowered:
        return "exterior"
    return None


def _explicit_storyboard_shot_count(text: str) -> tuple[int | None, str | None]:
    match = re.search(
        r"\b((one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
        r"(?:storyboard\s+)?shots?)\b",
        text,
        flags=re.I,
    )
    if match:
        return _count_value(match.group(2)), match.group(1).strip()
    return None, None


def _explicit_duration(text: str) -> tuple[int | None, str | None]:
    match = re.search(
        r"((\d{1,3})(?:-\s*|\s*)(?:second|seconds|s)\b)",
        text,
        flags=re.I,
    )
    if not match:
        return None, None
    return int(match.group(2)), match.group(1).strip()


def _aggregate_scene_count(text: str) -> tuple[int | None, str | None]:
    count_pattern = r"\d{1,2}|" + "|".join(re.escape(word) for word in _ENGLISH_COUNTS)
    match = re.search(
        rf"\b((?:use|with|include|create|exactly)\s+({count_pattern})\s+scenes?)\b",
        text,
        flags=re.I,
    )
    if match:
        return _count_value(match.group(2)), match.group(1).strip()
    labeled = re.search(
        rf"\bscenes?\s*:\s*({count_pattern})\s+scenes?\b",
        text,
        flags=re.I,
    )
    if labeled:
        return _count_value(labeled.group(1)), labeled.group(0).strip()
    return None, None


def _count_value(value: str | None) -> int | None:
    if not value:
        return None
    stripped = value.strip().lower()
    if stripped.isdigit():
        parsed = int(stripped)
        return parsed if parsed > 0 else None
    return _ENGLISH_COUNTS.get(stripped)


def _match_span(text: str, pattern: str, *, group: int = 0) -> str | None:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return None
    return match.group(group).strip()


def _find_span(text: str, value: str) -> str | None:
    pattern = re.escape(value.strip())
    return _match_span(text, pattern)


def _products_from_constraints(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
) -> list[V2IntentProduct]:
    product_name = explicit_constraints.product_name or request.product_name
    if not product_name:
        return []
    source_span = explicit_constraints.product_source_span
    explicit = bool(source_span)
    return [
        V2IntentProduct(
            product_id="product-1",
            display_name=product_name,
            category=_product_category(product_name),
            source="explicit" if explicit else "inferred",
            source_span=source_span,
            confidence=0.98 if explicit else 0.82,
            reason=(
                "Product identity is stated in the request text."
                if explicit
                else "Product identity comes from the structured planning request."
            ),
        )
    ]


def _characters_from_constraints(
    explicit_constraints: V2ExplicitConstraints,
) -> list[V2IntentCharacter]:
    if not explicit_constraints.characters:
        return []
    characters: list[V2IntentCharacter] = []
    for index, constraint in enumerate(explicit_constraints.characters, start=1):
        gender = constraint.gender
        display = (
            "Male character"
            if gender == "male"
            else "Female character"
            if gender == "female"
            else f"Character {index}"
        )
        characters.append(
            V2IntentCharacter(
                character_id=f"character-{index}",
                display_name=display,
                gender=gender,
                role="lead" if index == 1 else "supporting",
                source="explicit" if constraint.source_span else "inferred",
                source_span=constraint.source_span,
                confidence=0.95 if constraint.source_span else 0.72,
                reason="The prompt explicitly states the character requirement.",
            )
        )
    return characters


def _intent_scene_from_constraint(
    constraint: V2ExplicitSceneConstraint,
    index: int,
) -> V2IntentScene:
    return V2IntentScene(
        scene_id=f"scene-{index}",
        display_name=_scene_display_name(constraint.kind),
        kind=constraint.kind,
        time_of_day=constraint.time_of_day
        or ("night" if constraint.kind == "night_street" else None),
        setting_type=constraint.setting_type,
        source="explicit",
        source_span=constraint.source_span,
        confidence=0.95,
        reason="The prompt explicitly states the scene requirement.",
    )


def _default_characters(concept_mode: str) -> list[V2IntentCharacter]:
    count = {
        "product_only": 0,
        "spokesperson_demo": 1,
        "lifestyle_narrative": 2,
        "unclassified": 1,
    }[concept_mode]
    return [
        V2IntentCharacter(
            character_id=f"character-{index}",
            display_name=("Primary user representative" if count == 1 else f"Character {index}"),
            gender=None,
            role="lead" if index == 1 else "supporting",
            source="default",
            source_span=None,
            confidence=0.7,
            reason="The character count follows the concept-mode fallback policy.",
        )
        for index in range(1, count + 1)
    ]


def _default_scenes(count: int, *, start_index: int = 1) -> list[V2IntentScene]:
    kinds = ["product_lifestyle", "urban_lifestyle", "indoor", "outdoor"]
    return [
        V2IntentScene(
            scene_id=f"scene-{index}",
            display_name=_scene_display_name(kinds[(index - start_index) % len(kinds)]),
            kind=kinds[(index - start_index) % len(kinds)],
            source="default",
            source_span=None,
            confidence=0.7,
            reason="The scene count follows the storyboard fallback policy.",
        )
        for index in range(start_index, start_index + count)
    ]


def _storyboard_from_constraints(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
) -> V2IntentStoryboard:
    if explicit_constraints.storyboard_shot_count is not None:
        return V2IntentStoryboard(
            shot_count=explicit_constraints.storyboard_shot_count,
            source="explicit" if explicit_constraints.storyboard_shot_count_span else "inferred",
            source_span=explicit_constraints.storyboard_shot_count_span,
            confidence=0.96 if explicit_constraints.storyboard_shot_count_span else 0.82,
            reason="Storyboard shot count comes from explicit constraints.",
        )
    return V2IntentStoryboard(
        shot_count=max(1, ceil(request.duration_seconds / V2_MAX_SHOT_DURATION_SECONDS)),
        source="default",
        source_span=None,
        confidence=0.72,
        reason="The storyboard count follows requested duration and provider limits.",
    )


def _fallback_concept_mode(request: WorkflowV2PlanFromPromptRequest) -> str:
    value = request.metadata.get("concept_mode")
    if value in {
        "product_only",
        "spokesperson_demo",
        "lifestyle_narrative",
        "unclassified",
    }:
        return str(value)
    return "unclassified"


def _product_category(product_name: str) -> str | None:
    normalized = product_name.lower()
    if "iphone" in normalized or "phone" in normalized:
        return "smartphone"
    return None


def _scene_display_name(kind: str) -> str:
    if kind == "night_street":
        return "Night Street Scene"
    if kind == "product_lifestyle":
        return "Product Lifestyle Scene"
    return f"{kind.replace('_', ' ').title()} Scene"


def _intent_planner_system_prompt() -> str:
    return (
        "You are the V2 Intent Contract Planner. Return one JSON object matching V2IntentPlan. "
        "Preserve explicit user constraints for product, characters, scenes, storyboard shot count, "
        "duration, aspect ratio, and audio. Every core fact must include source provenance: "
        "source, source_span, confidence, and reason. System fields and schema keys must be English. "
        "Use concise English snake_case scene kinds matching ^[a-z][a-z0-9_]{0,63}$. "
        "Keep setting_type and time_of_day as separate technical facets. "
        "The user prompt may be Chinese or any other language."
    )


def _intent_planner_payload(
    *,
    request: WorkflowV2PlanFromPromptRequest,
    normalized_request: dict[str, Any] | None,
    explicit_constraints: V2ExplicitConstraints,
) -> dict[str, Any]:
    return sanitize_context_for_llm_text(
        {
            "task": "Create a validated V2IntentPlan before V2 workflow creation.",
            "request": request.model_dump(mode="json"),
            "front_desk_normalized_request": normalized_request or {},
            "explicit_constraints": explicit_constraints.model_dump(mode="json"),
            "requirements": {
                "preserve_explicit_character_count": True,
                "preserve_explicit_character_gender": True,
                "preserve_explicit_scene_kinds": True,
                "preserve_explicit_storyboard_shot_count": True,
                "do_not_generate_media": True,
                "system_language": "English",
            },
        }
    )


def _intent_repair_context(error: V2StructuredLLMError) -> dict[str, Any]:
    details = error.quality_error_details
    if isinstance(details, dict):
        return {"violations": details.get("violations") or []}
    return {}


def _runtime_error_code(exc: StructuredGenerationRuntimeError) -> str:
    if exc.code == "structured_generation_schema_failed":
        return "v2_intent_schema_invalid"
    if exc.code in {
        "structured_generation_quality_failed",
        "structured_generation_repair_failed",
    }:
        return "v2_intent_validation_failed"
    if exc.code == "structured_generation_fallback_failed":
        return "v2_intent_fallback_failed"
    return "v2_intent_schema_invalid"


def _iter_intent_facts(intent: V2IntentPlan) -> list[tuple[str, Any]]:
    facts: list[tuple[str, Any]] = []
    facts.extend((f"products.{index}", item) for index, item in enumerate(intent.products))
    facts.extend((f"characters.{index}", item) for index, item in enumerate(intent.characters))
    facts.extend((f"scenes.{index}", item) for index, item in enumerate(intent.scenes))
    facts.append(("storyboard", intent.storyboard))
    facts.append(("audio", intent.audio))
    return facts


def _violation(
    code: str,
    message: str,
    *,
    expected: Any = None,
    actual: Any = None,
    expected_kind: str | None = None,
    source_span: str | None = None,
    field_path: str | None = None,
    details: dict[str, Any] | None = None,
) -> V2IntentValidationViolation:
    return V2IntentValidationViolation(
        code=code,
        message=message,
        expected=expected,
        actual=actual,
        expected_kind=expected_kind,
        source_span=source_span,
        field_path=field_path,
        details=details or {},
    )


def validation_summary(validation: V2IntentValidationResult) -> dict[str, Any]:
    return {
        "valid": validation.valid,
        "violation_codes": [violation.code for violation in validation.violations],
        "violations": [violation.model_dump(mode="json") for violation in validation.violations],
    }


def model_json(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")
