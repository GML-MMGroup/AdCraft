"""Trusted schema and semantic validation for in-run Pi submissions."""

from __future__ import annotations

from typing import Any
import unicodedata

from pydantic import ValidationError

from app.persistence.agent_run_repository import AgentRunRecord, AgentRunRepository
from app.schemas.agent_runtime import (
    AgentStructuredNormalizationAuditV1,
    AgentStructuredSubmission,
    AgentStructuredValidationResult,
    StructuredViolation,
)
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthorityPlanV2,
)
from app.services.agent_canvas_role_prompt_compiler import role_prompt_text_violation
from app.services.v2_agent_contract_registry import (
    AgentStructuredContractRegistryError,
    validate_agent_contract,
)
from app.services.v2_agent_structured_normalization import (
    AGENT_STRUCTURED_NORMALIZATION_REGISTRY,
    AgentStructuredNormalizationResult,
)


class V2AgentStructuredValidationService:
    """Validate model-owned values against Python-owned durable run metadata."""

    def __init__(self, repository: AgentRunRepository) -> None:
        self._repository = repository

    def validate(
        self,
        *,
        run: AgentRunRecord,
        submission: AgentStructuredSubmission,
    ) -> AgentStructuredValidationResult:
        identity_violations = _identity_violations(run, submission)
        if identity_violations:
            return _rejected(submission, identity_violations)
        raw_semantic_violations = self._raw_semantic_violations(
            run,
            submission.value,
        )
        normalization = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
            run.contract_name or "",
            submission.value,
        )
        if normalization.violations:
            return _rejected(
                submission,
                normalization.violations + raw_semantic_violations,
            )

        try:
            normalized = validate_agent_contract(
                run.contract_name or "",
                normalization.value,
            )
        except ValidationError as error:
            return _rejected(
                submission,
                _project_validation_errors(error) + raw_semantic_violations,
            )
        except AgentStructuredContractRegistryError:
            return _rejected(
                submission,
                (
                    StructuredViolation(
                        code="agent_contract_not_allowed",
                        message="The persisted Agent contract is not registered.",
                        field_path="contract_name",
                    ),
                ),
                repair_allowed=False,
            )

        normalized_value = _canonicalize_profile_value(
            run.validation_profile,
            run.validation_context,
            normalized.model_dump(
                mode="json",
                exclude_unset=run.contract_name == "CompactTurnIntentDecisionV3",
            ),
        )
        if run.validation_profile == "canary_reject_first_v1":
            if submission.attempt == 1:
                return _rejected(
                    submission,
                    (
                        StructuredViolation(
                            code="canary_first_submission_rejected",
                            message="The verification canary requires one scoped repair.",
                        ),
                    ),
                )
            return AgentStructuredValidationResult(
                accepted=True,
                normalized_result_id=submission.submission_id,
                normalized_value=normalized_value,
                repair_allowed=False,
                normalization_audit=_normalization_audit(
                    run,
                    submission,
                    normalization,
                ),
            )
        semantic_violations = raw_semantic_violations + _semantic_violations(
            run.validation_profile,
            run.validation_context,
            normalized_value,
        )
        if semantic_violations:
            return _rejected(
                submission,
                semantic_violations,
                repair_allowed=(
                    False
                    if any(
                        item.code == "agent_validation_context_invalid"
                        for item in semantic_violations
                    )
                    else None
                ),
            )
        return AgentStructuredValidationResult(
            accepted=True,
            normalized_result_id=submission.submission_id,
            normalized_value=normalized_value,
            repair_allowed=False,
            normalization_audit=_normalization_audit(
                run,
                submission,
                normalization,
            ),
        )

    def _raw_semantic_violations(
        self,
        run: AgentRunRecord,
        value: dict[str, Any],
    ) -> tuple[StructuredViolation, ...]:
        if run.validation_profile != "agent_intake_source_quotes_v1":
            return ()
        source_turn_id = run.validation_context.get("source_turn_id")
        if not isinstance(source_turn_id, str) or not source_turn_id:
            return (_invalid_intake_validation_context(),)
        source_message = self._repository.load_validation_source_message(
            workflow_id=run.workflow_id,
            conversation_id=run.conversation_id,
            turn_id=source_turn_id,
        )
        if source_message is None:
            return (_invalid_intake_validation_context(),)
        return _intake_source_quote_violations(source_message, value)


def _identity_violations(
    run: AgentRunRecord,
    submission: AgentStructuredSubmission,
) -> tuple[StructuredViolation, ...]:
    if submission.run_id != run.run_id:
        return (
            StructuredViolation(
                code="agent_run_mismatch",
                message="The structured submission does not belong to this Agent run.",
                field_path="run_id",
            ),
        )
    if submission.contract_name != run.contract_name:
        return (
            StructuredViolation(
                code="agent_contract_mismatch",
                message="The structured submission contract does not match the Agent run.",
                field_path="contract_name",
                expected=run.contract_name,
                actual=submission.contract_name,
            ),
        )
    return ()


def _normalization_audit(
    run: AgentRunRecord,
    submission: AgentStructuredSubmission,
    normalization: AgentStructuredNormalizationResult,
) -> AgentStructuredNormalizationAuditV1 | None:
    if not normalization.rule_ids:
        return None
    return AgentStructuredNormalizationAuditV1(
        contract_name=run.contract_name or "",
        rule_ids=normalization.rule_ids,
        normalized_path_count=normalization.normalized_path_count,
        submission_attempt=submission.attempt,
    )


def _semantic_violations(
    profile: str | None,
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    if profile in {
        None,
        "schema_only_v1",
        "agent_intake_source_quotes_v1",
    }:
        return ()
    if profile == "video_parameter_intent_v3":
        return _video_parameter_intent_v3_violations(context, value)
    if profile == "style_skill_consultation_v1":
        allowed_ids = context.get("allowed_skill_ids")
        if not isinstance(allowed_ids, list) or not all(
            isinstance(item, str) for item in allowed_ids
        ):
            return (
                StructuredViolation(
                    code="agent_validation_context_invalid",
                    message="Public Style Skill facts are unavailable.",
                    field_path="validation_context",
                ),
            )
        referenced = value.get("referenced_skill_ids", [])
        if len(set(referenced)) != len(referenced) or not set(referenced).issubset(allowed_ids):
            return (
                StructuredViolation(
                    code="style_skill_reference_invalid",
                    message="Reference only IDs in the supplied public Style Skill facts.",
                    field_path="referenced_skill_ids",
                ),
            )
        if (
            value.get("answer_kind") not in {"general", "clarification"}
            or value.get("style_skill_audit") is not None
        ):
            return (
                StructuredViolation(
                    code="style_skill_answer_scope_invalid",
                    message="Preserve the read-only consultation scope; omit Python-owned audit metadata.",
                    field_path="answer_kind",
                ),
            )
        return ()
    if profile == "front_desk_core_v1":
        return _front_desk_core_violations(value)
    if profile == "storyboard_sequence_window_parity_v1":
        return _storyboard_sequence_window_violations(context, value)
    if profile == "proposal_candidate_count_v1":
        return _proposal_candidate_count_violations(context, value)
    if profile == "brand_form_supplemental_novelty_v1":
        return _brand_form_supplemental_novelty_violations(context, value)
    if profile == "brand_form_slots_v1":
        return _brand_form_slot_violations(context, value)
    if profile == "brand_treatment_review_sources_v1":
        return _brand_treatment_review_source_violations(context, value)
    if profile == "role_prompt_contract_v1":
        return _role_prompt_contract_violations(context, value)
    if profile != "frozen_fields_v1":
        return (
            StructuredViolation(
                code="agent_validation_profile_not_allowed",
                message="The persisted Agent validation profile is not registered.",
                field_path="validation_profile",
            ),
        )
    expected_values = context.get("expected_values")
    if not isinstance(expected_values, dict):
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The persisted Agent validation context is incomplete.",
                field_path="expected_values",
            ),
        )
    violations: list[StructuredViolation] = []
    for field_path, expected in expected_values.items():
        if not isinstance(field_path, str):
            continue
        actual = _value_at_path(value, field_path)
        if actual != expected:
            violations.append(
                StructuredViolation(
                    code="frozen_fact_mismatch",
                    message="The result changed a frozen explicit fact.",
                    field_path=field_path,
                    expected=expected,
                    actual=actual,
                )
            )
    return tuple(violations)


def _brand_form_supplemental_novelty_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    """Require each requested supplemental row to add genuinely new options."""

    requested_slot_ids = context.get("requested_slot_ids")
    previous_options_by_slot = context.get("previous_options_by_slot")
    minimum_new_options = context.get("minimum_new_options", 2)
    if (
        not isinstance(requested_slot_ids, list)
        or not requested_slot_ids
        or len(set(requested_slot_ids)) != len(requested_slot_ids)
        or not all(isinstance(slot_id, str) and slot_id for slot_id in requested_slot_ids)
        or not isinstance(previous_options_by_slot, dict)
        or not isinstance(minimum_new_options, int)
        or isinstance(minimum_new_options, bool)
        or minimum_new_options < 1
        or minimum_new_options > 3
    ):
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The supplemental Brand form validation context is incomplete.",
                field_path="validation_context",
            ),
        )

    previous_labels_by_slot: dict[str, set[str]] = {}
    for slot_id in requested_slot_ids:
        previous = previous_options_by_slot.get(slot_id)
        if not isinstance(previous, list) or not previous:
            return (
                StructuredViolation(
                    code="agent_validation_context_invalid",
                    message="Previous Brand form options are unavailable for a requested slot.",
                    field_path=f"previous_options_by_slot.{slot_id}",
                ),
            )
        labels: set[str] = set()
        for option in previous:
            if not isinstance(option, dict) or not isinstance(option.get("label"), str):
                return (
                    StructuredViolation(
                        code="agent_validation_context_invalid",
                        message="Previous Brand form options must contain labels.",
                        field_path=f"previous_options_by_slot.{slot_id}",
                    ),
                )
            labels.add(_normalized_form_option_label(option["label"]))
        previous_labels_by_slot[slot_id] = labels

    cards = value.get("form_cards")
    if not isinstance(cards, list):
        return (
            StructuredViolation(
                code="brand_form_supplemental_novelty_missing",
                message="Supplemental Brand form output must contain form cards.",
                field_path="form_cards",
            ),
        )
    cards_by_slot = {
        card.get("target_slot_id"): (index, card)
        for index, card in enumerate(cards)
        if isinstance(card, dict) and isinstance(card.get("target_slot_id"), str)
    }
    violations: list[StructuredViolation] = []
    for slot_id in requested_slot_ids:
        card_entry = cards_by_slot.get(slot_id)
        if card_entry is None:
            violations.append(
                StructuredViolation(
                    code="brand_form_supplemental_novelty_missing",
                    message="Supplemental Brand form output is missing a requested slot.",
                    field_path="form_cards",
                    expected=slot_id,
                )
            )
            continue
        card_index, card = card_entry
        options = card.get("options")
        labels = (
            [option.get("label") for option in options if isinstance(option, dict)]
            if isinstance(options, list)
            else []
        )
        normalized_labels = [
            _normalized_form_option_label(label)
            for label in labels
            if isinstance(label, str) and label.strip()
        ]
        novel_count = len(set(normalized_labels) - previous_labels_by_slot[slot_id])
        if (
            len(normalized_labels) != len(labels)
            or len(set(normalized_labels)) != len(normalized_labels)
            or novel_count < minimum_new_options
        ):
            violations.append(
                StructuredViolation(
                    code="brand_form_supplemental_novelty_missing",
                    message=(
                        "Each requested supplemental Brand form slot must contain "
                        f"at least {minimum_new_options} new options."
                    ),
                    field_path=f"form_cards.{card_index}.options",
                    expected={"minimum_new_options": minimum_new_options},
                    actual={"novel_option_count": novel_count},
                )
            )
    return tuple(violations)


def _brand_form_slot_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    """Require one generated form card for every authoritative foundation slot."""

    expected_slot_ids = context.get("expected_slot_ids")
    if (
        not isinstance(expected_slot_ids, list)
        or not expected_slot_ids
        or len(set(expected_slot_ids)) != len(expected_slot_ids)
        or not all(isinstance(slot_id, str) and slot_id for slot_id in expected_slot_ids)
    ):
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The Brand form slot validation context is incomplete.",
                field_path="validation_context.expected_slot_ids",
            ),
        )

    cards = value.get("form_cards")
    if not isinstance(cards, list):
        return (
            StructuredViolation(
                code="brand_form_slot_missing",
                message="Brand foundation form output must contain form cards.",
                field_path="form_cards",
                expected=expected_slot_ids,
            ),
        )
    cards_by_slot: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, card in enumerate(cards):
        if not isinstance(card, dict) or not isinstance(card.get("target_slot_id"), str):
            continue
        cards_by_slot.setdefault(str(card["target_slot_id"]), (index, card))
    return tuple(
        StructuredViolation(
            code="brand_form_slot_missing",
            message="Brand foundation form output is missing an authoritative slot.",
            field_path="form_cards",
            expected=slot_id,
        )
        for slot_id in expected_slot_ids
        if slot_id not in cards_by_slot
    )


def _brand_treatment_review_source_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    """Require every Treatment review source to quote confirmed text."""

    confirmed_sections = context.get("confirmed_sections")
    if not isinstance(confirmed_sections, list) or not confirmed_sections:
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="Confirmed Treatment sections are unavailable for review validation.",
                field_path="validation_context.confirmed_sections",
            ),
        )
    sections: dict[tuple[str, str], str] = {}
    for item in confirmed_sections:
        if not isinstance(item, dict):
            return (_invalid_brand_review_context(),)
        step_key = item.get("step_key")
        section_key = item.get("section_key")
        text = item.get("text")
        if not all(isinstance(field, str) and field for field in (step_key, section_key, text)):
            return (_invalid_brand_review_context(),)
        sections[(step_key, section_key)] = text

    violations: list[StructuredViolation] = []
    for field_path, source in _brand_treatment_review_sources(value):
        step_key = source.get("step_key")
        section_key = source.get("section_key")
        quote = source.get("quote")
        allowed_text = (
            sections.get((step_key, section_key))
            if isinstance(step_key, str) and isinstance(section_key, str)
            else None
        )
        if (
            not isinstance(quote, str)
            or not quote.strip()
            or not isinstance(allowed_text, str)
            or normalize_confirmed_quote(quote) not in normalize_confirmed_quote(allowed_text)
        ):
            safe_allowed = allowed_text or "No confirmed text exists for this section."
            safe_quote = quote if isinstance(quote, str) else ""
            if len(safe_allowed) > 400:
                safe_allowed = safe_allowed[:400] + "…"
            violations.append(
                StructuredViolation(
                    code="brand_review_source_quote_invalid",
                    message=(
                        "Copy the confirmed section text exactly after normalization. "
                        f"Invalid reference: step_key={step_key!r}, section_key={section_key!r}, "
                        f"bad quote={safe_quote!r}, allowed text={safe_allowed!r}."
                    ),
                    field_path=field_path,
                    expected=safe_allowed,
                    actual={
                        "step_key": step_key,
                        "section_key": section_key,
                        "quote": safe_quote,
                        "allowed_text": safe_allowed,
                    },
                )
            )
    return tuple(violations)


def _invalid_brand_review_context() -> StructuredViolation:
    return StructuredViolation(
        code="agent_validation_context_invalid",
        message="Confirmed Treatment sections must contain step, section, and text.",
        field_path="validation_context.confirmed_sections",
    )


def _brand_treatment_review_sources(
    value: dict[str, Any],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    found: list[tuple[str, dict[str, Any]]] = []
    requirements = value.get("production_requirements")
    if not isinstance(requirements, dict):
        return ()

    def add_sources(path: str, sources: Any) -> None:
        if not isinstance(sources, list):
            return
        for index, source in enumerate(sources):
            if isinstance(source, dict):
                found.append((f"{path}.{index}", source))

    add_sources("production_requirements.character_sources", requirements.get("character_sources"))
    add_sources("production_requirements.prop_sources", requirements.get("prop_sources"))
    add_sources("production_requirements.scene_sources", requirements.get("scene_sources"))
    for element_name in ("characters", "scenes"):
        elements = requirements.get(element_name)
        if not isinstance(elements, list):
            continue
        for element_index, element in enumerate(elements):
            if isinstance(element, dict):
                add_sources(
                    f"production_requirements.{element_name}.{element_index}.sources",
                    element.get("sources"),
                )
    findings = value.get("findings")
    if isinstance(findings, list):
        for finding_index, finding in enumerate(findings):
            if isinstance(finding, dict):
                add_sources(f"findings.{finding_index}.sources", finding.get("sources"))
    return tuple(found)


def normalize_confirmed_quote(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).strip()
    while normalized and unicodedata.category(normalized[0]).startswith("P"):
        normalized = normalized[1:].lstrip()
    while normalized and unicodedata.category(normalized[-1]).startswith("P"):
        normalized = normalized[:-1].rstrip()
    return normalized


def _normalized_form_option_label(label: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", label).split()).casefold()


def _role_prompt_contract_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    role_variant = context.get("role_variant")
    prompt_authority = context.get("prompt_authority")
    if not isinstance(role_variant, str) or prompt_authority not in {
        "system_generated",
        "user_authored",
    }:
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The persisted role-prompt validation context is incomplete.",
                field_path="validation_context",
            ),
        )
    if prompt_authority == "user_authored":
        return ()
    if role_variant == "scene_board":
        projection_digest = context.get("scene_projection_digest")
        projection_required = context.get("scene_projection_required", True)
        if not isinstance(projection_required, bool):
            return (
                StructuredViolation(
                    code="agent_validation_context_invalid",
                    message="The Scene projection requirement flag is invalid.",
                    field_path="scene_projection_required",
                ),
            )
        if projection_required and (
            not isinstance(projection_digest, str)
            or not projection_digest.startswith("sha256:")
            or len(projection_digest) != 71
            or any(character not in "0123456789abcdef" for character in projection_digest[7:])
        ):
            return (
                StructuredViolation(
                    code="agent_validation_context_invalid",
                    message="The frozen Scene projection identity is invalid.",
                    field_path="scene_projection_digest",
                ),
            )
    editable_prompt = value.get("editable_prompt")
    if not isinstance(editable_prompt, str):
        return ()
    violation = role_prompt_text_violation(
        role_variant,
        editable_prompt,
        field_path="editable_prompt",
    )
    if violation is None:
        return ()
    if role_variant == "scene_board":
        message = "The Scene brief conflicts with its environment-only role contract."
        expected = "environment_only"
    elif role_variant == "video_segment":
        message = "The video brief conflicts with its video-only role contract."
        expected = "video_without_background_music"
    else:
        message = "The role brief conflicts with its role contract."
        expected = "role_specific_content"
    return (
        StructuredViolation(
            code="node_prompt_role_contract_invalid",
            message=message,
            field_path=violation.field_path,
            expected=expected,
            actual=violation.violation_category,
        ),
    )


def _proposal_candidate_count_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    expected = context.get("expected_candidate_count")
    options = value.get("options")
    for identity_field in ("operation", "capability_id", "result_contract_name"):
        identity = context.get(identity_field)
        if not isinstance(identity, str) or not identity:
            return (
                StructuredViolation(
                    code="agent_validation_context_invalid",
                    message="The persisted proposal identity context is incomplete.",
                    field_path=identity_field,
                ),
            )
    if not isinstance(expected, int) or isinstance(expected, bool) or expected not in {1, 3}:
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The persisted proposal candidate-count context is invalid.",
                field_path="expected_candidate_count",
                expected="1 or 3",
                actual=expected,
            ),
        )
    if not isinstance(options, list):
        return (
            StructuredViolation(
                code="proposal_candidate_count_mismatch",
                message="The proposal result does not contain an options collection.",
                field_path="options",
                expected=expected,
                actual=None,
            ),
        )
    if len(options) != expected:
        return (
            StructuredViolation(
                code="proposal_candidate_count_mismatch",
                message="The proposal result count does not match the authoritative request.",
                field_path="options",
                expected=expected,
                actual=len(options),
            ),
        )
    return ()


def _storyboard_sequence_window_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    try:
        authority = StoryboardSequenceAuthorityPlanV2.model_validate(context)
    except (ValidationError, ValueError, TypeError):
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The persisted Storyboard Sequence authority plan is invalid.",
                field_path="validation_context",
            ),
        )

    violations: list[StructuredViolation] = []
    for field_name, expected in (
        ("aspect_ratio", authority.aspect_ratio),
        ("total_duration_seconds", authority.total_duration_seconds),
    ):
        actual = value.get(field_name)
        if actual != expected:
            violations.append(
                StructuredViolation(
                    code="storyboard_sequence_parameter_mismatch",
                    message="The Storyboard outline changed a frozen sequence parameter.",
                    field_path=field_name,
                    expected=expected,
                    actual=actual,
                )
            )

    segments = value.get("segments")
    if not isinstance(segments, list):
        return tuple(violations)
    if len(segments) != len(authority.windows):
        violations.append(
            StructuredViolation(
                code="storyboard_sequence_count_mismatch",
                message="The Storyboard outline changed the frozen sequence count.",
                field_path="segments",
                expected=len(authority.windows),
                actual=len(segments),
            )
        )

    for index, (segment, window) in enumerate(zip(segments, authority.windows)):
        if not isinstance(segment, dict):
            continue
        if segment.get("order") != window.order:
            violations.append(
                StructuredViolation(
                    code="storyboard_sequence_order_mismatch",
                    message="The Storyboard outline changed a frozen sequence order.",
                    field_path=f"segments.{index}.order",
                    expected=window.order,
                    actual=segment.get("order"),
                )
            )
        for field_name, expected in (
            ("start_seconds", window.start_seconds),
            ("end_seconds", window.end_seconds),
        ):
            actual = segment.get(field_name)
            if actual != expected:
                violations.append(
                    StructuredViolation(
                        code="storyboard_sequence_timing_mismatch",
                        message="The Storyboard outline changed a frozen sequence boundary.",
                        field_path=f"segments.{index}.{field_name}",
                        expected=expected,
                        actual=actual,
                    )
                )
    return tuple(violations)


def _invalid_intake_validation_context() -> StructuredViolation:
    return StructuredViolation(
        code="agent_validation_context_invalid",
        message="The persisted Agent validation context is incomplete.",
        field_path="source_turn_id",
    )


def _safe_violation_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2_048]
    if isinstance(value, BaseException):
        return str(value)[:1_024]
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            str(key)[:160]: _safe_violation_value(item, depth=depth + 1)
            for key, item in tuple(value.items())[:16]
        }
    if isinstance(value, (list, tuple)):
        return [_safe_violation_value(item, depth=depth + 1) for item in value[:16]]
    return type(value).__name__


def _project_validation_errors(
    error: ValidationError,
) -> tuple[StructuredViolation, ...]:
    errors = error.errors()
    retained = tuple(item for item in errors if not _is_derived_too_short(item, errors))
    return tuple(
        StructuredViolation(
            code=str(item["type"]),
            message=str(item["msg"]),
            field_path=".".join(str(part) for part in item["loc"]) or None,
            expected=_project_expected_value(item.get("ctx")),
            actual=_safe_violation_value(item.get("input")),
        )
        for item in retained
    )


def _is_derived_too_short(
    item: dict[str, Any],
    errors: list[dict[str, Any]],
) -> bool:
    if item.get("type") != "too_short":
        return False
    raw_collection = item.get("input")
    context = item.get("ctx")
    if not isinstance(raw_collection, (list, tuple)) or not isinstance(context, dict):
        return False
    minimum = context.get("min_length")
    if not isinstance(minimum, int) or len(raw_collection) < minimum:
        return False
    location = tuple(item.get("loc") or ())
    return any(
        other is not item
        and len(tuple(other.get("loc") or ())) > len(location)
        and tuple(other.get("loc") or ())[: len(location)] == location
        for other in errors
    )


def _project_expected_value(context: Any) -> Any:
    if isinstance(context, dict) and "expected" in context:
        return _safe_violation_value(context["expected"])
    return _safe_violation_value(context)


def _intake_source_quote_violations(
    source_message: str,
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    normalized_message = unicodedata.normalize("NFKC", source_message)
    violations: list[StructuredViolation] = []
    for field_path, quote in _intake_source_quotes(value):
        if unicodedata.normalize("NFKC", quote) in normalized_message:
            continue
        violations.append(
            StructuredViolation(
                code="requirement_source_quote_invalid",
                message="Requirement evidence must quote the current user message exactly.",
                field_path=field_path,
                expected="exact substring of the current user message",
                actual=quote,
            )
        )
    return tuple(violations)


def _intake_source_quotes(value: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    quotes: list[tuple[str, str]] = []
    requirement_patch = value.get("requirement_patch")
    if isinstance(requirement_patch, dict):
        controls = requirement_patch.get("controls_to_set")
        if isinstance(controls, dict):
            for control_name, control in controls.items():
                if isinstance(control, dict) and isinstance(control.get("source_quote"), str):
                    quotes.append(
                        (
                            f"requirement_patch.controls_to_set.{control_name}.source_quote",
                            control["source_quote"],
                        )
                    )
        directives = requirement_patch.get("directives_to_add")
        if isinstance(directives, list):
            quotes.extend(
                (
                    f"requirement_patch.directives_to_add.{index}.source_quote",
                    directive["source_quote"],
                )
                for index, directive in enumerate(directives)
                if isinstance(directive, dict) and isinstance(directive.get("source_quote"), str)
            )
    explicit_elements = value.get("explicit_elements")
    if isinstance(explicit_elements, dict):
        quotes.extend(
            (f"explicit_elements.{element_kind}.source_quote", element["source_quote"])
            for element_kind, element in explicit_elements.items()
            if isinstance(element, dict) and isinstance(element.get("source_quote"), str)
        )
    return tuple(quotes)


def _canonicalize_profile_value(
    profile: str | None,
    context: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    if profile != "front_desk_core_v1":
        return value
    if value.get("intent") not in {"ready_for_workflow", "ad_request"}:
        return value
    ad_request = value.get("ad_request")
    fallback = context.get("fallback_product_description")
    if (
        isinstance(ad_request, dict)
        and not str(ad_request.get("product_description") or "").strip()
        and isinstance(fallback, str)
        and fallback.strip()
    ):
        value = dict(value)
        value["ad_request"] = {
            **ad_request,
            "product_description": fallback.strip()[:1_000],
        }
    return value


def _front_desk_core_violations(
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    if value.get("intent") not in {"ready_for_workflow", "ad_request"}:
        return ()
    ad_request = value.get("ad_request")
    if not isinstance(ad_request, dict):
        return (
            StructuredViolation(
                code="front_desk_core_field_missing",
                message="Workflow creation requires a structured advertising request.",
                field_path="ad_request",
            ),
        )
    violations: list[StructuredViolation] = []
    for field_name in ("product_name", "product_description", "target_audience"):
        field_value = ad_request.get(field_name)
        if field_value is None or not str(field_value).strip():
            violations.append(
                StructuredViolation(
                    code="front_desk_core_field_missing",
                    message="Workflow creation is missing required advertising information.",
                    field_path=f"ad_request.{field_name}",
                )
            )
    return tuple(violations)


def _video_parameter_intent_v3_violations(
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    unresolved = set(context.get("unresolved_fields") or ())
    source_refs = set(context.get("source_refs") or ())
    violations: list[StructuredViolation] = []
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        return ()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        field = candidate.get("field")
        source_ref = candidate.get("source_ref")
        if field not in unresolved:
            violations.append(
                StructuredViolation(
                    code="field_already_resolved",
                    message="The candidate field is not unresolved in this request.",
                    field_path=f"candidates.{index}.field",
                )
            )
        if source_ref not in source_refs:
            violations.append(
                StructuredViolation(
                    code="source_ref_not_allowed",
                    message="The candidate source_ref was not supplied in this request.",
                    field_path=f"candidates.{index}.source_ref",
                )
            )
    return tuple(violations)


def _value_at_path(value: dict[str, Any], field_path: str) -> Any:
    current: Any = value
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _rejected(
    submission: AgentStructuredSubmission,
    violations: tuple[StructuredViolation, ...],
    *,
    repair_allowed: bool | None = None,
) -> AgentStructuredValidationResult:
    return AgentStructuredValidationResult(
        accepted=False,
        violations=violations,
        repair_allowed=(submission.attempt < 2 if repair_allowed is None else repair_allowed),
    )
