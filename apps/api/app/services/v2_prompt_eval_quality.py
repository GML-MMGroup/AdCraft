from __future__ import annotations

import re
from typing import Any

from app.schemas.workflow_v2 import V2GenerationTarget
from app.schemas.workflow_v2_prompt_eval import (
    V2PromptEvalQualityFailure,
    V2PromptEvalStage,
)
from app.services.v2_specialist_configs import specialist_model_env_key_for
from app.services.v2_specialist_ownership import validate_specialist_slot_target


HARD_FAILURE_CODES = {
    "schema_validity",
    "reference_payload_safety",
    "provider_payload_safety",
    "specialist_model_not_configured",
    "specialist_ownership_violation",
    "specialist_slot_plan_invalid",
    "specialist_wrong_model_env_key",
    "storyboard_detail_payload_unsafe",
    "no_raw_prompt_wrapper",
    "reference_audit_missing",
    "reference_audit_required_reference_missing",
    "reference_audit_submitted_reference_missing",
    "reference_audit_submitted_reference_not_allowed",
    "reference_audit_provider_payload_mismatch",
    "reference_audit_unexplained_drop",
    "reference_audit_payload_unsafe",
    "reference_audit_provider_capability_missing",
    "provider_request_capture_missing",
    "provider_prompt_mismatch",
    "provider_payload_legacy_empty_template",
    "provider_payload_product_drift",
    "prompt_isolation_audit_missing",
    "prompt_isolation_audit_failed",
    "v2_provider_prompt_registry_ref_missing",
    "v2_prompt_lineage_missing",
}

RAW_PROMPT_WRAPPERS = (
    "30s ad script for",
    "Product image prompt:",
    "Character image prompt:",
    "Scene image prompt:",
    "Professional storyboard detail for:",
    "Dialogue direction for:",
    "Audio atmosphere for:",
)
FORBIDDEN_CHARACTER_MAIN_TERMS = (
    "three-view",
    "three view",
    "turnaround",
    "sheet",
    "grid",
    "contact sheet",
    "collage",
)
MUSIC_TERMS = ("bgm", "music", "soundtrack", "lyrics", "vocals", "bgm generation")
SENSITIVE_KEYS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "raw_bytes",
    "raw_response",
    "file_content",
    "base64",
    "data_url",
)
LEGACY_EMPTY_TEMPLATE_MARKERS = (
    "Location: .",
    "Lighting: .",
    "Atmosphere: .",
    "Shot: .",
    "Visual: .",
    "Camera: .",
    "Action: .",
)


class V2PromptEvalQualityService:
    def evaluate_text(
        self,
        *,
        stage: V2PromptEvalStage,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        text: str | None,
        expected_language: str | None = None,
    ) -> list[V2PromptEvalQualityFailure]:
        failures: list[V2PromptEvalQualityFailure] = []
        value = (text or "").strip()
        if not value:
            failures.append(
                self._failure(
                    "schema_validity",
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Prompt text is empty.",
                    evidence=None,
                )
            )
            return failures

        lower = value.lower()
        wrapper = next(
            (pattern for pattern in RAW_PROMPT_WRAPPERS if pattern.lower() in lower),
            None,
        )
        if wrapper:
            failures.append(
                self._failure(
                    "no_raw_prompt_wrapper",
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message=f"Prompt contains raw wrapper pattern: {wrapper}",
                    evidence=wrapper,
                )
            )

        if len(value) > 6_000:
            failures.append(
                self._failure(
                    "prompt_length_budget",
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Prompt exceeds the deterministic eval length budget.",
                    evidence=str(len(value)),
                )
            )

        failures.extend(
            self._slot_layout_failures(
                stage=stage,
                item_id=item_id,
                slot_id=slot_id,
                slot_type=slot_type,
                text=value,
            )
        )
        if expected_language:
            failures.extend(
                self._language_failures(
                    stage=stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    text=value,
                    expected_language=expected_language,
                )
            )
        return failures

    def evaluate_expert_briefs(
        self, prompts_by_role: dict[str, str]
    ) -> list[V2PromptEvalQualityFailure]:
        failures: list[V2PromptEvalQualityFailure] = []
        normalized = {
            role: _normalize_text(prompt) for role, prompt in prompts_by_role.items() if prompt
        }
        roles = sorted(normalized)
        for index, left_role in enumerate(roles):
            for right_role in roles[index + 1 :]:
                left = normalized[left_role]
                right = normalized[right_role]
                if left == right or _token_similarity(left, right) >= 0.92:
                    for failure_code in (
                        "expert_brief_prompts_too_similar",
                        "slot_specificity",
                    ):
                        failures.append(
                            self._failure(
                                failure_code,
                                "expert_brief",
                                item_id=f"{left_role}:{right_role}",
                                slot_id=None,
                                slot_type=None,
                                message=(
                                    "Expert brief prompts are too similar across distinct media roles."
                                ),
                                evidence=f"{left_role}<->{right_role}",
                            )
                        )
        return failures

    def evaluate_storyboard_cells(
        self,
        *,
        shot_id: str,
        cell_prompts: list[str],
    ) -> list[V2PromptEvalQualityFailure]:
        failures: list[V2PromptEvalQualityFailure] = []
        if len([prompt for prompt in cell_prompts if prompt.strip()]) != 4:
            failures.append(
                self._failure(
                    "storyboard_detail_missing_cell_prompt",
                    "storyboard_detail_prompts",
                    item_id=shot_id,
                    slot_id=None,
                    slot_type=None,
                    message="Storyboard detail stage must produce exactly four cell prompts.",
                    evidence=str(len(cell_prompts)),
                )
            )
        normalized = [_normalize_text(prompt) for prompt in cell_prompts if prompt.strip()]
        unique = set(normalized)
        if len(normalized) >= 2 and len(unique) <= max(1, len(normalized) // 2):
            failures.extend(
                [
                    self._failure(
                        "storyboard_detail_duplicate_cell_prompts",
                        "storyboard_detail_prompts",
                        item_id=shot_id,
                        slot_id=None,
                        slot_type=None,
                        message="Storyboard cell prompts are duplicated and do not show progression.",
                        evidence=str(len(unique)),
                    ),
                    self._failure(
                        "storyboard_progression",
                        "storyboard_detail_prompts",
                        item_id=shot_id,
                        slot_id=None,
                        slot_type=None,
                        message="Storyboard cell prompts are duplicated and do not show progression.",
                        evidence=str(len(unique)),
                    ),
                ]
            )
        unsafe_paths = _unsafe_payload_paths(cell_prompts)
        if unsafe_paths:
            failures.append(
                self._failure(
                    "storyboard_detail_payload_unsafe",
                    "storyboard_detail_prompts",
                    item_id=shot_id,
                    slot_id=None,
                    slot_type=None,
                    message="Storyboard cell prompts contain raw media, data URLs, oversized content, or secret-like fields.",
                    evidence=", ".join(unsafe_paths[:8]),
                )
            )
        return failures

    def evaluate_storyboard_video_detail(
        self,
        *,
        shot_id: str,
        prompt: str,
        detail_prompts: dict[str, Any],
        selected_cell_asset_ids: list[str],
    ) -> list[V2PromptEvalQualityFailure]:
        failures: list[V2PromptEvalQualityFailure] = []
        combined = " ".join(
            [
                prompt,
                str(detail_prompts.get("dialogue") or ""),
                str(detail_prompts.get("audio_description") or ""),
                str(detail_prompts.get("voice_style") or ""),
                str(detail_prompts.get("video_negative_constraints") or ""),
            ]
        )
        missing: list[str] = []
        if not detail_prompts.get("time_segments"):
            missing.append("time_segments")
        if not _contains_any(combined, ("second", "seconds", "0-", "0.0-", "duration")):
            missing.append("duration")
        if not _contains_any(combined, ("camera", "lens", "framing", "push", "pan", "tilt")):
            missing.append("camera")
        if not _contains_any(combined, ("action", "beat", "move", "gesture", "reveal")):
            missing.append("action")
        if "dialogue" not in detail_prompts and "dialogue:" not in combined.lower():
            missing.append("dialogue")
        if "audio_description" not in detail_prompts and "audio" not in combined.lower():
            missing.append("audio")
        if "voice_style" not in detail_prompts and "voice" not in combined.lower():
            missing.append("voice")
        if (
            "video_negative_constraints" not in detail_prompts
            and "negative" not in combined.lower()
        ):
            missing.append("negative_constraints")
        if not selected_cell_asset_ids:
            missing.append("selected_cell_refs")
        if missing:
            failures.append(
                self._failure(
                    "storyboard_video_detail_completeness",
                    "storyboard_detail_prompts",
                    item_id=shot_id,
                    slot_id=f"{shot_id}:shot_video_segment",
                    slot_type="shot_video_segment",
                    message="Storyboard video detail prompt is missing required fields.",
                    evidence=", ".join(missing),
                )
            )
            if "time_segments" in missing:
                failures.append(
                    self._failure(
                        "storyboard_detail_missing_video_timeline",
                        "storyboard_detail_prompts",
                        item_id=shot_id,
                        slot_id=f"{shot_id}:shot_video_segment",
                        slot_type="shot_video_segment",
                        message="Storyboard video detail is missing timeline segments.",
                        evidence="time_segments",
                    )
                )
        if _invalid_storyboard_video_duration(detail_prompts):
            failures.append(
                self._failure(
                    "storyboard_detail_invalid_duration",
                    "storyboard_detail_prompts",
                    item_id=shot_id,
                    slot_id=f"{shot_id}:shot_video_segment",
                    slot_type="shot_video_segment",
                    message="Storyboard video timeline must cover a supported 5s or 10s duration.",
                    evidence="duration",
                )
            )
        if _contains_any(combined, MUSIC_TERMS):
            for failure_code in (
                "storyboard_detail_music_contamination",
                "storyboard_video_audio_scope",
            ):
                failures.append(
                    self._failure(
                        failure_code,
                        "storyboard_detail_prompts",
                        item_id=shot_id,
                        slot_id=f"{shot_id}:shot_video_segment",
                        slot_type="shot_video_segment",
                        message="Storyboard video prompt asks for music/BGM instead of video-only detail.",
                        evidence="music_scope",
                    )
                )
        unsafe_paths = _unsafe_payload_paths(
            {
                "prompt": prompt,
                "detail_prompts": detail_prompts,
                "selected_cell_asset_ids": selected_cell_asset_ids,
            }
        )
        if unsafe_paths:
            failures.append(
                self._failure(
                    "storyboard_detail_payload_unsafe",
                    "storyboard_detail_prompts",
                    item_id=shot_id,
                    slot_id=f"{shot_id}:shot_video_segment",
                    slot_type="shot_video_segment",
                    message="Storyboard video detail contains raw media, data URLs, oversized content, or secret-like fields.",
                    evidence=", ".join(unsafe_paths[:8]),
                )
            )
        return failures

    def evaluate_payload(
        self,
        *,
        stage: V2PromptEvalStage,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        payload: dict[str, Any],
    ) -> list[V2PromptEvalQualityFailure]:
        failure_code = (
            "reference_payload_safety" if stage == "reference_bundle" else "provider_payload_safety"
        )
        failures: list[V2PromptEvalQualityFailure] = []
        unsafe_paths = list(_unsafe_payload_paths(payload))
        if unsafe_paths:
            failures.append(
                self._failure(
                    failure_code,
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Payload contains raw media, data URLs, oversized content, or secret-like fields.",
                    evidence=", ".join(unsafe_paths[:8]),
                )
            )
        if stage == "provider_payload":
            failures.extend(
                self._provider_payload_prompt_registry_failures(
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    payload=payload,
                )
            )
            failures.extend(
                self._provider_payload_ownership_failures(
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    payload=payload,
                )
            )
            failures.extend(
                self._provider_payload_reference_audit_failures(
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    payload=payload,
                )
            )
            failures.extend(
                self._provider_payload_prompt_integrity_failures(
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    payload=payload,
                )
            )
        return failures

    def _provider_payload_prompt_registry_failures(
        self,
        *,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        payload: dict[str, Any],
    ) -> list[V2PromptEvalQualityFailure]:
        failures: list[V2PromptEvalQualityFailure] = []
        ref = payload.get("prompt_registry_ref")
        lineage = payload.get("prompt_lineage")
        metadata = _prompt_failure_metadata(payload)
        if not isinstance(ref, dict) or not str(ref.get("prompt_id") or "").strip():
            failures.append(
                self._failure(
                    "v2_provider_prompt_registry_ref_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload is missing prompt_registry_ref.",
                    evidence="prompt_registry_ref",
                    prompt_metadata=metadata,
                )
            )
        if not isinstance(lineage, dict) or not isinstance(
            lineage.get("prompt_registry_ref"), dict
        ):
            failures.append(
                self._failure(
                    "v2_prompt_lineage_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload is missing prompt_lineage.",
                    evidence="prompt_lineage",
                    prompt_metadata=metadata,
                )
            )
        return failures

    def _provider_payload_ownership_failures(
        self,
        *,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        payload: dict[str, Any],
    ) -> list[V2PromptEvalQualityFailure]:
        route = payload.get("agent_route")
        target_payload = payload.get("target")
        failures: list[V2PromptEvalQualityFailure] = []
        if not isinstance(route, dict) or not isinstance(target_payload, dict):
            return failures
        specialist = route.get("specialist")
        if not isinstance(specialist, str) or not specialist:
            return failures
        target = V2GenerationTarget(
            workflow_id=str(
                target_payload.get("workflow_id") or payload.get("workflow_id") or "wf"
            ),
            target_type=target_payload.get("target_type") or "slot",
            node_id=target_payload.get("node_id"),
            node_type=target_payload.get("node_type"),
            item_id=target_payload.get("item_id") or item_id,
            item_type=target_payload.get("item_type"),
            slot_id=target_payload.get("slot_id") or slot_id,
            slot_type=target_payload.get("slot_type") or slot_type,
            asset_id=target_payload.get("asset_id"),
            media_type=target_payload.get("media_type"),
            is_free_generation=bool(target_payload.get("is_free_generation")),
        )
        validation = validate_specialist_slot_target(
            specialist=specialist,
            target=target,
            action=_payload_action(payload, target),
        )
        if not validation.valid:
            failures.append(
                self._failure(
                    validation.error_code or "specialist_ownership_violation",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message=validation.error_message
                    or "Provider payload specialist ownership validation failed.",
                    evidence=", ".join(validation.violations[:8]),
                )
            )
        expected_env_key = specialist_model_env_key_for(specialist)
        actual_env_key = payload.get("model_env_key")
        if expected_env_key and actual_env_key and actual_env_key != expected_env_key:
            failures.append(
                self._failure(
                    "specialist_wrong_model_env_key",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload uses a model env key outside the routed specialist.",
                    evidence=f"{specialist}:{actual_env_key}!={expected_env_key}",
                )
            )
        return failures

    def _provider_payload_reference_audit_failures(
        self,
        *,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        payload: dict[str, Any],
    ) -> list[V2PromptEvalQualityFailure]:
        audit = payload.get("reference_audit")
        if not isinstance(audit, dict):
            return [
                self._failure(
                    "reference_audit_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload is missing reference_audit.",
                    evidence="reference_audit",
                )
            ]
        failures: list[V2PromptEvalQualityFailure] = []
        unsafe_paths = _unsafe_payload_paths(audit)
        if unsafe_paths:
            failures.append(
                self._failure(
                    "reference_audit_payload_unsafe",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Reference audit contains raw media, data URLs, oversized content, or secret-like fields.",
                    evidence=", ".join(unsafe_paths[:8]),
                )
            )
        payload_reference_ids = _string_list(payload.get("reference_asset_ids"))
        submitted = _string_list(audit.get("submitted_reference_asset_ids"))
        requested = set(_string_list(audit.get("requested_reference_asset_ids")))
        required = set(_string_list(audit.get("required_reference_asset_ids")))
        allowed = set(_string_list(audit.get("allowed_reference_asset_ids")))
        dropped = set(_string_list(audit.get("dropped_reference_asset_ids")))
        drop_reason_ids = {
            str(reason.get("asset_id"))
            for reason in audit.get("drop_reasons", [])
            if isinstance(reason, dict) and str(reason.get("asset_id") or "")
        }
        if payload_reference_ids != submitted:
            failures.append(
                self._failure(
                    "reference_audit_provider_payload_mismatch",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload reference_asset_ids differ from reference_audit submitted references.",
                    evidence="reference_asset_ids",
                )
            )
        if payload_reference_ids and not submitted:
            failures.append(
                self._failure(
                    "reference_audit_submitted_reference_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload has references but audit submitted references are empty.",
                    evidence="submitted_reference_asset_ids",
                )
            )
        if allowed and any(asset_id not in allowed for asset_id in submitted):
            failures.append(
                self._failure(
                    "reference_audit_submitted_reference_not_allowed",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Reference audit submitted a reference outside the slot context allowlist.",
                    evidence="allowed_reference_asset_ids",
                )
            )
        if not required.issubset(requested):
            failures.append(
                self._failure(
                    "reference_audit_required_reference_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Required reference ids are not included in requested references.",
                    evidence="required_reference_asset_ids",
                )
            )
        if not required.issubset(set(submitted)):
            failures.append(
                self._failure(
                    "reference_audit_required_reference_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Required reference ids are not included in submitted references.",
                    evidence="submitted_reference_asset_ids",
                )
            )
        unexplained = sorted(dropped - drop_reason_ids)
        if unexplained:
            failures.append(
                self._failure(
                    "reference_audit_unexplained_drop",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Dropped reference ids must have drop_reasons entries.",
                    evidence=", ".join(unexplained[:8]),
                )
            )
        if (submitted or dropped) and not isinstance(
            audit.get("provider_capability_snapshot"), dict
        ):
            failures.append(
                self._failure(
                    "reference_audit_provider_capability_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Reference audit is missing provider capability snapshot.",
                    evidence="provider_capability_snapshot",
                )
            )
        elif (submitted or dropped) and not audit.get("provider_capability_snapshot"):
            failures.append(
                self._failure(
                    "reference_audit_provider_capability_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Reference audit provider capability snapshot is empty.",
                    evidence="provider_capability_snapshot",
                )
            )
        return failures

    def _provider_payload_prompt_integrity_failures(
        self,
        *,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        payload: dict[str, Any],
    ) -> list[V2PromptEvalQualityFailure]:
        failures: list[V2PromptEvalQualityFailure] = []
        audit = payload.get("prompt_isolation_audit")
        if not isinstance(audit, dict):
            failures.append(
                self._failure(
                    "prompt_isolation_audit_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload is missing prompt_isolation_audit.",
                    evidence="prompt_isolation_audit",
                )
            )
        elif audit.get("valid") is not True:
            failures.append(
                self._failure(
                    "prompt_isolation_audit_failed",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload prompt isolation audit is not valid.",
                    evidence=str(audit.get("error_code") or "prompt_isolation_audit"),
                )
            )

        capture = payload.get("provider_request_capture")
        capture_required = bool(payload.get("prompt_eval_capture_required"))
        if capture_required and not isinstance(capture, dict):
            failures.append(
                self._failure(
                    "provider_request_capture_missing",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload eval requires captured provider request metadata.",
                    evidence="provider_request_capture",
                )
            )
        if isinstance(capture, dict):
            canonical_prompt = _canonical_provider_prompt(payload, capture)
            actual_prompt = str(capture.get("actual_provider_request_prompt") or "").strip()
            prompt_match = capture.get("prompt_match")
            if canonical_prompt and actual_prompt:
                prompts_match = canonical_prompt.strip() == actual_prompt
                if prompt_match is False or not prompts_match:
                    failures.append(
                        self._failure(
                            "provider_prompt_mismatch",
                            "provider_payload",
                            item_id=item_id,
                            slot_id=slot_id,
                            slot_type=slot_type,
                            message=(
                                "Captured provider request prompt differs from the canonical provider prompt."
                            ),
                            evidence="provider_request_capture.actual_provider_request_prompt",
                        )
                    )
            elif capture_required:
                failures.append(
                    self._failure(
                        "provider_request_capture_missing",
                        "provider_payload",
                        item_id=item_id,
                        slot_id=slot_id,
                        slot_type=slot_type,
                        message="Captured provider request prompt is missing.",
                        evidence="actual_provider_request_prompt",
                    )
                )

        legacy_markers = _legacy_empty_template_markers(payload)
        if legacy_markers:
            failures.append(
                self._failure(
                    "provider_payload_legacy_empty_template",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload contains empty legacy prompt template markers.",
                    evidence=", ".join(legacy_markers[:8]),
                )
            )
        drift_terms = _product_drift_terms(payload)
        if drift_terms:
            failures.append(
                self._failure(
                    "provider_payload_product_drift",
                    "provider_payload",
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Provider payload contains fixture-forbidden product drift terms.",
                    evidence=", ".join(drift_terms[:8]),
                )
            )
        return failures

    def _slot_layout_failures(
        self,
        *,
        stage: V2PromptEvalStage,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        text: str,
    ) -> list[V2PromptEvalQualityFailure]:
        if not slot_type:
            return []
        lower = text.lower()
        if slot_type == "character_main_image" and _has_positive_forbidden_term(
            lower, FORBIDDEN_CHARACTER_MAIN_TERMS
        ):
            return [
                self._failure(
                    "slot_layout_correctness",
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Character main image prompt asks for a multi-view or sheet layout.",
                    evidence=slot_type,
                )
            ]
        if slot_type == "scene_multi_view_grid":
            required = ("2x2", "four", "establishing", "environment", "background")
            if not all(term in lower for term in required):
                return [
                    self._failure(
                        "slot_layout_correctness",
                        stage,
                        item_id=item_id,
                        slot_id=slot_id,
                        slot_type=slot_type,
                        message="Scene multi-view prompt must specify a 2x2 four-view grid.",
                        evidence="missing_2x2_four_view_grid",
                    )
                ]
        return []

    def _language_failures(
        self,
        *,
        stage: V2PromptEvalStage,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        text: str,
        expected_language: str,
    ) -> list[V2PromptEvalQualityFailure]:
        normalized = expected_language.lower()
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
        if normalized == "english" and has_cjk:
            return [
                self._failure(
                    "language_policy",
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="English fixture produced visible CJK text.",
                    evidence="cjk_detected",
                )
            ]
        if normalized == "chinese" and not has_cjk:
            return [
                self._failure(
                    "language_policy",
                    stage,
                    item_id=item_id,
                    slot_id=slot_id,
                    slot_type=slot_type,
                    message="Chinese fixture produced no visible CJK text.",
                    evidence="cjk_missing",
                )
            ]
        return []

    def _failure(
        self,
        failure_code: str,
        stage: V2PromptEvalStage,
        *,
        item_id: str | None,
        slot_id: str | None,
        slot_type: str | None,
        message: str,
        evidence: str | None,
        prompt_metadata: dict[str, Any] | None = None,
    ) -> V2PromptEvalQualityFailure:
        prompt_metadata = prompt_metadata or {}
        return V2PromptEvalQualityFailure(
            failure_code=failure_code,
            message=message,
            stage=stage,
            item_id=item_id,
            slot_id=slot_id,
            slot_type=slot_type,
            gate=failure_code,
            hard_failure=failure_code in HARD_FAILURE_CODES,
            evidence=evidence,
            prompt_id=prompt_metadata.get("prompt_id"),
            prompt_version=prompt_metadata.get("prompt_version"),
            owner=prompt_metadata.get("owner"),
            prompt_scope=prompt_metadata.get("scope"),
            path_kind=prompt_metadata.get("path_kind"),
        )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower())).strip()


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    normalized = value.lower()
    return any(term in normalized for term in terms)


def _canonical_provider_prompt(payload: dict[str, Any], capture: dict[str, Any]) -> str:
    prompt = payload.get("provider_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    prompt = capture.get("canonical_provider_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    canonical = payload.get("canonical_provider_payload")
    if isinstance(canonical, dict):
        prompt = canonical.get("provider_prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
    return ""


def _prompt_failure_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    ref = payload.get("prompt_registry_ref")
    lineage = payload.get("prompt_lineage")
    if not isinstance(ref, dict) and isinstance(lineage, dict):
        lineage_ref = lineage.get("prompt_registry_ref")
        if isinstance(lineage_ref, dict):
            ref = lineage_ref
    ref = ref if isinstance(ref, dict) else {}
    lineage = lineage if isinstance(lineage, dict) else {}
    return {
        "prompt_id": ref.get("prompt_id") or lineage.get("prompt_id"),
        "prompt_version": ref.get("prompt_version") or lineage.get("prompt_version"),
        "owner": ref.get("owner") or lineage.get("owner"),
        "scope": ref.get("scope") or lineage.get("scope"),
        "path_kind": lineage.get("path_kind"),
    }


def _legacy_empty_template_markers(payload: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    for value in _payload_text_values(payload, excluded_keys={"prompt_eval_forbidden_terms"}):
        for marker in LEGACY_EMPTY_TEMPLATE_MARKERS:
            if marker.lower() in value.lower():
                markers.append(marker)
    return list(dict.fromkeys(markers))


def _product_drift_terms(payload: dict[str, Any]) -> list[str]:
    forbidden_terms = [
        str(term).strip().lower()
        for term in payload.get("prompt_eval_forbidden_terms", [])
        if str(term).strip()
    ]
    if not forbidden_terms:
        return []
    combined = " ".join(
        _payload_text_values(payload, excluded_keys={"prompt_eval_forbidden_terms"})
    ).lower()
    return list(dict.fromkeys(term for term in forbidden_terms if term in combined))


def _payload_text_values(value: Any, *, excluded_keys: set[str] | None = None) -> list[str]:
    excluded_keys = excluded_keys or set()
    if isinstance(value, dict):
        texts: list[str] = []
        for key, item in value.items():
            if str(key) in excluded_keys:
                continue
            texts.extend(_payload_text_values(item, excluded_keys=excluded_keys))
        return texts
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            texts.extend(_payload_text_values(item, excluded_keys=excluded_keys))
        return texts
    if isinstance(value, str):
        return [value]
    return []


def _payload_action(payload: dict[str, Any], target: V2GenerationTarget) -> str:
    explicit = payload.get("action")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    route = payload.get("agent_route")
    if isinstance(route, dict):
        route_action = route.get("action")
        if isinstance(route_action, str) and route_action.strip():
            return route_action.strip()
    slot_type = target.slot_type or ""
    if slot_type == "shot_video_segment":
        return "materialize_shot_video"
    if slot_type.startswith("shot_cell_"):
        return "materialize_shot_cells"
    if slot_type == "final_video":
        return "build_timeline"
    if slot_type == "free_output":
        return "free_generate"
    return "materialize_item_slots"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in (str(raw).strip() for raw in value) if item))


def _invalid_storyboard_video_duration(detail_prompts: dict[str, Any]) -> bool:
    segments = detail_prompts.get("time_segments")
    if not isinstance(segments, list) or not segments:
        return False
    try:
        starts = [
            float(segment["start_seconds"]) for segment in segments if isinstance(segment, dict)
        ]
        ends = [float(segment["end_seconds"]) for segment in segments if isinstance(segment, dict)]
    except (KeyError, TypeError, ValueError):
        return True
    if len(starts) != len(segments) or len(ends) != len(segments):
        return True
    if starts[0] != 0:
        return True
    if any(end <= start for start, end in zip(starts, ends, strict=False)):
        return True
    if any(left > right for left, right in zip(ends, starts[1:], strict=False)):
        return True
    return ends[-1] not in {5.0, 10.0}


def _has_positive_forbidden_term(value: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        start = value.find(term)
        while start >= 0:
            prefix = value[max(0, start - 18) : start]
            if not re.search(r"\b(no|without|avoid|exclude|not)\b", prefix):
                return True
            start = value.find(term, start + len(term))
    return False


def _unsafe_payload_paths(value: Any, *, prefix: str = "$") -> list[str]:
    unsafe: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}"
            if any(sensitive in key_text for sensitive in SENSITIVE_KEYS):
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
