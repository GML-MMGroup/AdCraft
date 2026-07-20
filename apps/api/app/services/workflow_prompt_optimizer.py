import json
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.agents.advertising import (
    build_bgm_agent,
    build_character_designer_agent,
    build_final_video_generation_agent,
    build_product_designer_agent,
    build_scene_designer_agent,
    build_storyboard_agent,
)
from app.agents.prompt_optimizers import PROMPT_OPTIMIZER_AGENT_BY_NODE
from app.core.config import Settings
from app.schemas.prompt_optimization import (
    PromptOptimizationRequest,
    PromptOptimizationResult,
)
from app.services.agno_orchestrator import _run_agent
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text_with_warnings
from app.services.provider_identity_certification import model_id_for_provider
from app.skills.loader import SkillLoadError, load_skill
from app.skills.registry import SKILL_IDS_BY_NODE


class WorkflowPromptOptimizerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class WorkflowPromptOptimizerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def optimize(self, request: PromptOptimizationRequest) -> PromptOptimizationResult:
        request = _sanitize_prompt_optimization_request(request)
        optimizer_agent = optimizer_agent_for_node(request.node_type)
        selected_skills, warnings, skill_outputs = self._select_and_trace_skills(
            request,
            optimizer_agent,
        )
        warnings = [*request.warnings, *warnings]
        model_id: str | None = None
        try:
            if self._settings.agno_mock_mode:
                result = self._mock_result(
                    request,
                    optimizer_agent=optimizer_agent,
                    selected_skill_ids=selected_skills,
                    warnings=warnings,
                )
            else:
                result, model_id = self._real_result(
                    request,
                    optimizer_agent=optimizer_agent,
                    selected_skill_ids=selected_skills,
                    warnings=warnings,
                    skill_outputs=skill_outputs,
                )
        except WorkflowPromptOptimizerError as exc:
            self._trace_optimizer(request, None, error=f"{exc.code}: {exc}")
            raise
        self._trace_optimizer(request, result, error=None, model_id=model_id)
        return result

    def normalize_result(
        self,
        request: PromptOptimizationRequest,
        payload: dict[str, Any],
    ) -> PromptOptimizationResult:
        normalized = dict(payload)
        warnings = list(normalized.get("warnings") or [])
        optimized = str(normalized.get("optimized_generation_prompt") or "").strip()
        provider_prompt = str(normalized.get("provider_prompt") or "").strip()
        if not optimized:
            raise WorkflowPromptOptimizerError(
                "prompt_optimizer_invalid_output",
                "Prompt optimizer returned empty optimized_generation_prompt.",
            )
        if not provider_prompt:
            provider_prompt = optimized
            warnings.append(
                {
                    "code": "prompt_optimizer_provider_prompt_empty",
                    "message": "provider_prompt was empty; optimized_generation_prompt was used.",
                }
            )
        normalized["optimized_generation_prompt"] = optimized
        normalized["provider_prompt"] = provider_prompt
        normalized["optimizer_agent"] = normalized.get(
            "optimizer_agent"
        ) or optimizer_agent_for_node(request.node_type)
        normalized["selected_skill_ids"] = list(normalized.get("selected_skill_ids") or [])
        normalized["mock_mode"] = bool(normalized.get("mock_mode", False))
        normalized["warnings"] = warnings
        try:
            return PromptOptimizationResult.model_validate(normalized)
        except ValidationError as exc:
            raise WorkflowPromptOptimizerError(
                "prompt_optimizer_invalid_output",
                str(exc),
            ) from exc

    def _mock_result(
        self,
        request: PromptOptimizationRequest,
        *,
        optimizer_agent: str,
        selected_skill_ids: list[str],
        warnings: list[dict[str, Any]],
    ) -> PromptOptimizationResult:
        base_prompt = _prompt_seed(request)
        asset_ids = [
            str(asset.get("asset_id"))
            for asset in request.resolved_input_assets
            if asset.get("asset_id")
        ]
        asset_note = (
            f"Use reference assets: {', '.join(asset_ids)}."
            if asset_ids
            else "No external reference assets were provided."
        )
        optimized_prompt = (
            f"{optimizer_agent} optimized prompt for {request.node_type}: "
            f"{base_prompt.strip()} {asset_note} "
            "Keep product identity, visual continuity, and commercial clarity."
        )
        provider_prompt = (
            f"{optimized_prompt} Provider instructions: generate production-ready media "
            f"for {request.node_type}."
        )
        return PromptOptimizationResult(
            optimized_generation_prompt=optimized_prompt,
            provider_prompt=provider_prompt,
            negative_prompt="low quality, distorted product, inconsistent branding",
            asset_references=asset_ids,
            quality_notes="Mock optimizer output.",
            optimizer_agent=optimizer_agent,
            selected_skill_ids=selected_skill_ids,
            mock_mode=True,
            warnings=[
                *warnings,
                {
                    "code": "prompt_optimizer_mock_mode",
                    "message": "Deterministic mock prompt optimizer output was used.",
                },
            ],
        )

    def _real_result(
        self,
        request: PromptOptimizationRequest,
        *,
        optimizer_agent: str,
        selected_skill_ids: list[str],
        warnings: list[dict[str, Any]],
        skill_outputs: dict[str, dict[str, Any]],
    ) -> tuple[PromptOptimizationResult, str | None]:
        try:
            payload = self._run_real_optimizer_payload(
                request,
                optimizer_agent,
                selected_skill_ids,
                skill_outputs,
            )
        except WorkflowPromptOptimizerError:
            if request.allow_optimizer_fallback:
                fallback_warning = {
                    "code": "prompt_optimizer_fallback_used",
                    "message": (
                        "Real prompt optimizer is unavailable; deterministic fallback was used."
                    ),
                }
                return self._mock_result(
                    request,
                    optimizer_agent=optimizer_agent,
                    selected_skill_ids=selected_skill_ids,
                    warnings=[*warnings, fallback_warning],
                ), None
            raise
        model_id = _resolved_prompt_optimizer_model_id(
            request.selected_provider,
            request.node_type,
            request.provider_media_type,
            self._settings,
        )
        payload = self._coerce_real_payload(
            payload,
            request,
            optimizer_agent,
            selected_skill_ids,
        )
        payload["warnings"] = [*warnings, *list(payload.get("warnings") or [])]
        return self.normalize_result(request, payload), model_id

    def _run_real_optimizer_payload(
        self,
        request: PromptOptimizationRequest,
        optimizer_agent: str,
        selected_skill_ids: list[str],
        skill_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | str:
        del optimizer_agent
        context = _real_optimizer_context(request, selected_skill_ids, skill_outputs)
        task = _build_optimizer_task(request, selected_skill_ids=selected_skill_ids)
        try:
            agent = _build_optimizer_agent(request.node_type, self._settings)
            output = _run_agent(
                agent=agent,
                output_model=PromptOptimizationResult,
                task=task,
                context=context,
                trace_writer=AgentTraceWriter(self._settings.media_data_dir, request.workflow_id),
                node_id=request.node_id,
            )
            return output.model_dump(mode="json")
        except WorkflowPromptOptimizerError:
            raise
        except Exception as exc:
            raise WorkflowPromptOptimizerError(
                "prompt_optimizer_real_mode_unavailable",
                f"Real prompt optimizer is unavailable: {exc}",
            ) from exc

    def _repair_real_optimizer_payload(
        self,
        raw_payload: str,
        request: PromptOptimizationRequest,
        optimizer_agent: str,
        selected_skill_ids: list[str],
    ) -> dict[str, Any] | None:
        del request, optimizer_agent, selected_skill_ids
        repaired = _repair_json_like_payload(raw_payload)
        if repaired is not None:
            return repaired
        if not raw_payload:
            return None
        return None

    def _coerce_real_payload(
        self,
        payload: dict[str, Any] | str,
        request: PromptOptimizationRequest,
        optimizer_agent: str,
        selected_skill_ids: list[str],
    ) -> dict[str, Any]:
        if isinstance(payload, dict):
            return dict(payload)
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError as exc:
                repaired = self._repair_real_optimizer_payload(
                    payload,
                    request,
                    optimizer_agent,
                    selected_skill_ids,
                )
                if repaired is None:
                    raise WorkflowPromptOptimizerError(
                        "prompt_optimizer_invalid_output",
                        f"Prompt optimizer returned invalid JSON: {exc}",
                    ) from exc
                return repaired
            if isinstance(decoded, dict):
                return decoded
        raise WorkflowPromptOptimizerError(
            "prompt_optimizer_invalid_output",
            "Prompt optimizer returned an unsupported output shape.",
        )

    def _select_and_trace_skills(
        self,
        request: PromptOptimizationRequest,
        optimizer_agent: str,
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, dict[str, Any]]]:
        requested_skill_ids, selection_reason = _requested_skill_ids(request)
        selected_skill_ids: list[str] = []
        warnings: list[dict[str, Any]] = []
        outputs: dict[str, dict[str, Any]] = {}
        trace_writer = AgentTraceWriter(self._settings.media_data_dir, request.workflow_id)
        for skill_id in requested_skill_ids:
            started_at = utc_now()
            started_counter = perf_counter()
            error: str | None = None
            selection_error: str | None = None
            skill_name = skill_id
            source_path: str | None = None
            prompt = f"Skill load failed before prompt construction: {skill_id}"
            output: dict[str, Any] = {"summary": "Skill failed", "key_points": []}
            try:
                skill = load_skill(skill_id)
                skill_name = skill.name
                source_path = skill.source_path.as_posix()
                output = skill.apply(_skill_context(request))
                prompt = skill.build_prompt(_skill_context(request))
            except SkillLoadError as exc:
                if "not found" in str(exc):
                    warnings.append(
                        {
                            "code": "prompt_optimizer_skill_not_found",
                            "skill_id": skill_id,
                            "message": (
                                "The recommended optimizer skill was not found and was skipped."
                            ),
                        }
                    )
                    selection_error = "prompt_optimizer_skill_not_found"
                    error = f"{selection_error}: {exc}"
                    output = {
                        "summary": "Recommended optimizer skill was not found and was skipped.",
                        "key_points": [],
                        "selection_error": selection_error,
                    }
                    continue
                error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 - trace skill errors before skipping.
                error = f"{type(exc).__name__}: {exc}"
            finally:
                if source_path is not None or error is not None:
                    trace_writer.append(
                        agent=optimizer_agent,
                        model=None,
                        prompt=prompt,
                        output=output,
                        error=error,
                        started_at=started_at,
                        finished_at=utc_now(),
                        duration_ms=round((perf_counter() - started_counter) * 1000),
                        metadata={
                            "trace_role": "skill",
                            "core_agent": optimizer_agent,
                            "skill_id": skill_id,
                            "skill_name": skill_name,
                            "skill_source_path": source_path,
                            "node_id": request.node_id,
                            "node_type": request.node_type,
                            "selection_reason": selection_reason,
                            "selection_error": selection_error,
                            "mode": "mock" if self._settings.agno_mock_mode else "real",
                            "input_summary": output.get("key_points", []),
                            "output_summary": output.get("summary"),
                        },
                    )
            if error is None:
                selected_skill_ids.append(skill_id)
                outputs[skill_id] = output
        return selected_skill_ids, warnings, outputs

    def _trace_optimizer(
        self,
        request: PromptOptimizationRequest,
        result: PromptOptimizationResult | None,
        *,
        error: str | None,
        model_id: str | None = None,
    ) -> None:
        trace_writer = AgentTraceWriter(self._settings.media_data_dir, request.workflow_id)
        started_at = utc_now()
        trace_writer.append(
            agent=result.optimizer_agent if result else optimizer_agent_for_node(request.node_type),
            model=None,
            prompt=json.dumps(_prompt_input_summary(request), ensure_ascii=False),
            output=result.model_dump(mode="json") if result else None,
            error=error,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=0,
            metadata={
                "trace_role": "prompt_optimizer",
                "workflow_id": request.workflow_id,
                "node_id": request.node_id,
                "node_type": request.node_type,
                "mode": request.mode,
                "optimizer_agent": result.optimizer_agent
                if result
                else optimizer_agent_for_node(request.node_type),
                "selected_skill_ids": result.selected_skill_ids if result else [],
                "model_id": model_id,
                "mock_mode": result.mock_mode if result else self._settings.agno_mock_mode,
                "prompt_input_summary": _prompt_input_summary(request),
            },
        )


def optimizer_agent_for_node(node_type: str) -> str:
    if node_type not in PROMPT_OPTIMIZER_AGENT_BY_NODE:
        raise WorkflowPromptOptimizerError(
            "prompt_optimizer_not_supported",
            f"node_type does not support prompt optimization: {node_type}",
        )
    return PROMPT_OPTIMIZER_AGENT_BY_NODE[node_type]


def _sanitize_prompt_optimization_request(
    request: PromptOptimizationRequest,
) -> PromptOptimizationRequest:
    warnings: list[dict[str, Any]] = list(request.warnings)
    updates: dict[str, Any] = {}
    try:
        for field_name in (
            "director_context",
            "resolved_input_context",
            "resolved_input_assets",
            "upstream_structured_outputs",
            "asset_references",
            "provider_capability_summary",
            "reference_policy_summary",
            "identity_certification_summary",
            "target_context",
        ):
            sanitized, field_warnings = sanitize_context_for_llm_text_with_warnings(
                getattr(request, field_name)
            )
            updates[field_name] = sanitized
            warnings.extend(field_warnings)
    except Exception as exc:
        raise WorkflowPromptOptimizerError(
            "llm_context_sanitization_failed",
            "Failed to sanitize prompt optimizer context for LLM text.",
        ) from exc
    updates["warnings"] = _dedupe_warnings(warnings)
    return request.model_copy(update=updates)


def _dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for warning in warnings:
        code = str(warning.get("code") or "")
        key = (code, json.dumps(warning, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _build_optimizer_agent(node_type: str, settings: Settings) -> Any:
    if node_type == "product-generation":
        return build_product_designer_agent(settings)
    if node_type == "character-generation":
        return build_character_designer_agent(settings)
    if node_type == "scene-generation":
        return build_scene_designer_agent(settings)
    if node_type == "storyboard":
        return build_storyboard_agent(settings)
    if node_type == "storyboard-video-generation":
        # TODO: replace with dedicated video optimizer agent when added.
        return build_final_video_generation_agent(settings)
    if node_type == "bgm":
        return build_bgm_agent(settings)
    raise WorkflowPromptOptimizerError(
        "prompt_optimizer_not_supported",
        f"node_type does not support real prompt optimization: {node_type}",
    )


def _build_optimizer_task(
    request: PromptOptimizationRequest,
    *,
    selected_skill_ids: list[str],
) -> str:
    if request.node_type == "storyboard-video-generation":
        return (
            "Optimize storyboard-based video scenes into a segment-level provider prompt package. "
            "Return valid JSON for this schema: "
            "optimized_generation_prompt, provider_prompt, negative_prompt, "
            "asset_references, reference_requirements, provider_parameters, continuity_constraints, "
            "quality_notes, optimizer_agent, selected_skill_ids, mock_mode, warnings. "
            "optimized_generation_prompt and provider_prompt must be non-empty. "
            "The output should be directly consumable by video segment generation; keep scene order "
            "and segment duration explicit. "
            f"node_id={request.node_id}, node_type={request.node_type}, "
            f"skills={', '.join(selected_skill_ids) if selected_skill_ids else 'none'}."
        )
    return (
        "Optimize the input into a provider-ready prompt package. "
        "Return valid JSON for this schema: "
        "optimized_generation_prompt, provider_prompt, negative_prompt, "
        "asset_references, reference_requirements, provider_parameters, continuity_constraints, "
        "quality_notes, optimizer_agent, selected_skill_ids, mock_mode, warnings. "
        "optimized_generation_prompt and provider_prompt must be non-empty. "
        f"node_id={request.node_id}, node_type={request.node_type}, "
        f"skills={', '.join(selected_skill_ids) if selected_skill_ids else 'none'}."
    )


def _real_optimizer_context(
    request: PromptOptimizationRequest,
    selected_skill_ids: list[str],
    skill_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "user_prompt": request.user_prompt,
        "system_suggested_prompt": request.system_suggested_prompt,
        "materialized_prompt": request.materialized_prompt,
        "override_prompt": request.override_prompt,
        "resolved_input_context": request.resolved_input_context,
        "resolved_input_assets": request.resolved_input_assets,
        "upstream_structured_outputs": request.upstream_structured_outputs,
        "director_context": request.director_context,
        "asset_references": request.asset_references,
        "provider_media_type": request.provider_media_type,
        "provider_capability_summary": request.provider_capability_summary,
        "reference_policy_summary": request.reference_policy_summary,
        "identity_certification_summary": request.identity_certification_summary,
        "selected_provider": request.selected_provider,
        "target_context": request.target_context,
        "selected_skill_ids": selected_skill_ids,
        "skill_guidance": [
            {"skill_id": skill_id, **(payload if isinstance(payload, dict) else {})}
            for skill_id, payload in skill_outputs.items()
        ],
    }


def _requested_skill_ids(request: PromptOptimizationRequest) -> tuple[tuple[str, ...], str]:
    groups = request.director_context.get("recommended_skill_groups")
    if isinstance(groups, dict):
        node_skills = groups.get(request.node_id)
        if isinstance(node_skills, list):
            return tuple(str(item) for item in node_skills), "director_context.node_id"
        type_skills = groups.get(request.node_type)
        if isinstance(type_skills, list):
            return tuple(str(item) for item in type_skills), "director_context.node_type"
    return tuple(SKILL_IDS_BY_NODE.get(request.node_type, ())), "node_type_default"


def _resolved_prompt_optimizer_model_id(
    selected_provider: str | None,
    node_type: str,
    provider_media_type: str | None,
    settings: Settings,
) -> str | None:
    if selected_provider is None:
        if node_type in {
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
        }:
            selected_provider = "mock_image" if settings.agno_mock_mode else "volcengine_image"
        elif node_type == "storyboard-video-generation":
            selected_provider = "mock_video" if settings.agno_mock_mode else "volcengine_video"
        elif node_type == "bgm":
            selected_provider = "mock_bgm" if settings.agno_mock_mode else "volcengine_audio"
        else:
            selected_provider = provider_media_type
    if selected_provider is None:
        return None
    return model_id_for_provider(selected_provider, settings)


def _repair_json_like_payload(payload: str) -> dict[str, Any] | None:
    text = payload.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if "{" not in text or "}" not in text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        loaded = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _prompt_seed(request: PromptOptimizationRequest) -> str:
    for value in (
        request.user_prompt,
        request.override_prompt,
        request.system_suggested_prompt,
        request.materialized_prompt,
        request.resolved_input_context.get("system_suggested_prompt"),
    ):
        if isinstance(value, str) and value.strip():
            return value
    return f"Create media for {request.node_type}."


def _skill_context(request: PromptOptimizationRequest) -> dict[str, Any]:
    return {
        "workflow_id": request.workflow_id,
        "node_id": request.node_id,
        "node_type": request.node_type,
        "mode": request.mode,
        "user_prompt": request.user_prompt,
        "system_suggested_prompt": request.system_suggested_prompt,
        "materialized_prompt": request.materialized_prompt,
        "override_prompt": request.override_prompt,
        "director_context": request.director_context,
        "resolved_input_context": request.resolved_input_context,
        "resolved_input_assets": request.resolved_input_assets,
        "asset_references": request.asset_references,
        "target_context": request.target_context,
    }


def _prompt_input_summary(request: PromptOptimizationRequest) -> dict[str, Any]:
    return {
        "mode": request.mode,
        "user_prompt": request.user_prompt,
        "system_suggested_prompt": request.system_suggested_prompt,
        "asset_ids": [
            str(asset.get("asset_id"))
            for asset in request.resolved_input_assets
            if asset.get("asset_id")
        ],
        "target_context": request.target_context,
    }
