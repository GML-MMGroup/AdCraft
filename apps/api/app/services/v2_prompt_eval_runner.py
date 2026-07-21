from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2PlanningClarificationResponse,
    WorkflowV2PlanFromPromptRequest,
)
from app.schemas.workflow_v2_planning import V2ExpertBriefPlan
from app.schemas.workflow_v2_screenplay import V2ScriptPlanV2
from app.schemas.workflow_v2_prompt_eval import (
    V2PromptEvalComparisonReport,
    V2PromptEvalComparisonRequest,
    V2PromptEvalFixture,
    V2PromptEvalMode,
    V2PromptEvalPromptOutput,
    V2PromptEvalQualityFailure,
    V2PromptEvalReport,
    V2PromptEvalStage,
    V2PromptEvalStageResult,
    V2PromptEvalStatus,
)
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_generation_pipeline import V2GenerationPipeline
from app.services.v2_generation_integrity import extract_planning_constraints
from app.services.v2_prompt_eval_quality import V2PromptEvalQualityService
from app.services.v2_prompt_profiles import (
    V2PromptProfileError,
    V2PromptProfileRegistry,
)
from app.services.v2_script_persistence import V2ScriptPersistenceAdapter
from app.services.v2_specialist_asset_prompt_quality import (
    V2SpecialistAssetPromptQualityValidator,
)
from app.services.v2_storyboard_director import V2StoryboardDirector
from app.services.v2_workflow_store import V2WorkflowStore


PROMPT_EVAL_STAGES: tuple[V2PromptEvalStage, ...] = (
    "script_writer",
    "expert_brief",
    "specialist_prompts",
    "storyboard_detail_prompts",
    "reference_bundle",
    "provider_payload",
)


class V2PromptEvalError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2PromptEvalRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        fixture_dir: Path | None = None,
        profile_registry: V2PromptProfileRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._fixture_dir = fixture_dir or _default_fixture_dir()
        self._profiles = profile_registry or V2PromptProfileRegistry()
        self._quality = V2PromptEvalQualityService()

    def list_fixtures(self) -> list[V2PromptEvalFixture]:
        return [
            self._load_fixture(path.stem)
            for path in sorted(self._fixture_dir.glob("*.json"))
            if path.is_file()
        ]

    def run_fixture(
        self,
        fixture_id: str,
        prompt_profile_id: str = "current",
        mode: V2PromptEvalMode = "mock",
        selected_stages: list[V2PromptEvalStage] | None = None,
    ) -> V2PromptEvalReport:
        if mode == "workflow_acceptance":
            return self._run_acceptance_fixture(
                fixture_id,
                prompt_profile_id=prompt_profile_id,
                selected_stages=selected_stages,
            )
        fixture = self._load_fixture(fixture_id)
        profile = self._profile(prompt_profile_id)
        stages = _normalize_stages(selected_stages or ["all"])
        eval_run_id = _new_eval_run_id()
        created_at = _utc_now()
        try:
            context = self._build_fixture_context(fixture, profile.profile_id, mode)
            stage_results = self._evaluate_context(
                context=context,
                profile_id=profile.profile_id,
                selected_stages=stages,
                expected_language=fixture.expected_language,
            )
            report = V2PromptEvalReport(
                eval_run_id=eval_run_id,
                status=_report_status(stage_results),
                mode=mode,
                profile_id=profile.profile_id,
                fixture_id=fixture.fixture_id,
                workflow_id=context.workflow.workflow_id,
                selected_stages=stages,
                stages=stage_results,
                failures=_collect_failures(stage_results),
                created_at=created_at,
            )
        except V2PromptEvalError:
            raise
        except Exception as exc:  # noqa: BLE001 - eval errors are persisted as controlled reports.
            report = V2PromptEvalReport(
                eval_run_id=eval_run_id,
                status="error",
                mode=mode,
                profile_id=prompt_profile_id,
                fixture_id=fixture.fixture_id,
                selected_stages=stages,
                stages=[],
                failures=[],
                created_at=created_at,
                error_code="prompt_eval_stage_failed",
                error_message=str(exc),
            )
        return self._persist_report(report)

    def replay_workflow(
        self,
        workflow_id: str,
        prompt_profile_id: str = "current",
        mode: str = "mock",
        selected_stages: list[V2PromptEvalStage] | None = None,
    ) -> V2PromptEvalReport:
        if mode == "workflow_acceptance":
            return self._replay_acceptance_workflow(
                workflow_id,
                prompt_profile_id=prompt_profile_id,
                selected_stages=selected_stages,
            )
        profile = self._profile(prompt_profile_id)
        stages = _normalize_stages(selected_stages or ["all"])
        eval_run_id = _new_eval_run_id()
        workflow = V2WorkflowStore(self._data_dir).load_workflow(workflow_id).model_copy(deep=True)
        try:
            context = self._build_replay_context(workflow, profile.profile_id)
            stage_results = self._evaluate_context(
                context=context,
                profile_id=profile.profile_id,
                selected_stages=stages,
                expected_language=None,
            )
            report = V2PromptEvalReport(
                eval_run_id=eval_run_id,
                status=_report_status(stage_results),
                mode="mock",
                profile_id=profile.profile_id,
                workflow_id=workflow_id,
                selected_stages=stages,
                stages=stage_results,
                failures=_collect_failures(stage_results),
                created_at=_utc_now(),
            )
        except Exception as exc:  # noqa: BLE001 - replay failures are controlled reports.
            report = V2PromptEvalReport(
                eval_run_id=eval_run_id,
                status="error",
                mode="mock",
                profile_id=profile.profile_id,
                workflow_id=workflow_id,
                selected_stages=stages,
                stages=[],
                failures=[],
                created_at=_utc_now(),
                error_code="prompt_eval_replay_not_supported",
                error_message=str(exc),
            )
        return self._persist_report(report)

    def _run_acceptance_fixture(
        self,
        fixture_id: str,
        *,
        prompt_profile_id: str,
        selected_stages: list[V2PromptEvalStage] | None,
    ) -> V2PromptEvalReport:
        from app.services.v2_workflow_acceptance import V2WorkflowAcceptanceRunner

        profile = self._profile(prompt_profile_id)
        stages = _normalize_stages(selected_stages or ["all"])
        acceptance_report = V2WorkflowAcceptanceRunner(self._settings).run_fixture(fixture_id)
        report = V2PromptEvalReport(
            eval_run_id=_new_eval_run_id(),
            status=acceptance_report.status,
            mode="workflow_acceptance",
            profile_id=profile.profile_id,
            fixture_id=fixture_id,
            workflow_id=acceptance_report.workflow_id,
            selected_stages=stages,
            stages=[],
            failures=[],
            created_at=_utc_now(),
            error_code=None
            if acceptance_report.status == "passed"
            else "workflow_acceptance_failed",
            error_message=None
            if acceptance_report.status == "passed"
            else "Deterministic workflow acceptance failed.",
            acceptance_report=acceptance_report,
        )
        return self._persist_report(report)

    def _replay_acceptance_workflow(
        self,
        workflow_id: str,
        *,
        prompt_profile_id: str,
        selected_stages: list[V2PromptEvalStage] | None,
    ) -> V2PromptEvalReport:
        from app.services.v2_workflow_acceptance import V2WorkflowAcceptanceRunner

        profile = self._profile(prompt_profile_id)
        stages = _normalize_stages(selected_stages or ["all"])
        acceptance_report = V2WorkflowAcceptanceRunner(self._settings).replay_workflow(workflow_id)
        report = V2PromptEvalReport(
            eval_run_id=_new_eval_run_id(),
            status=acceptance_report.status,
            mode="workflow_acceptance",
            profile_id=profile.profile_id,
            workflow_id=workflow_id,
            fixture_id=acceptance_report.fixture_id,
            selected_stages=stages,
            stages=[],
            failures=[],
            created_at=_utc_now(),
            error_code=None
            if acceptance_report.status == "passed"
            else "workflow_acceptance_failed",
            error_message=None
            if acceptance_report.status == "passed"
            else "Deterministic workflow acceptance failed.",
            acceptance_report=acceptance_report,
        )
        return self._persist_report(report)

    def compare_profiles(
        self,
        request: V2PromptEvalComparisonRequest,
    ) -> V2PromptEvalComparisonReport:
        baseline = self._profile(request.baseline_profile_id)
        candidate = self._profile(request.candidate_profile_id)
        fixture_ids = request.fixture_ids or [
            fixture.fixture_id for fixture in self.list_fixtures()
        ]
        stages = _normalize_stages(request.selected_stages or ["all"])
        baseline_reports = [
            self.run_fixture(
                fixture_id,
                prompt_profile_id=baseline.profile_id,
                mode=request.mode,
                selected_stages=stages,
            )
            for fixture_id in fixture_ids
        ]
        candidate_reports = [
            self.run_fixture(
                fixture_id,
                prompt_profile_id=candidate.profile_id,
                mode=request.mode,
                selected_stages=stages,
            )
            for fixture_id in fixture_ids
        ]
        regressions = _hard_regressions(baseline_reports, candidate_reports)
        status: V2PromptEvalStatus = "failed" if regressions else "passed"
        report = V2PromptEvalComparisonReport(
            eval_run_id=_new_eval_run_id(),
            status=status,
            baseline_profile_id=baseline.profile_id,
            candidate_profile_id=candidate.profile_id,
            fixture_ids=fixture_ids,
            mode=request.mode,
            selected_stages=stages,
            baseline_reports=baseline_reports,
            candidate_reports=candidate_reports,
            regressions=regressions,
            created_at=_utc_now(),
            error_code="prompt_eval_ab_regression_failed" if regressions else None,
            error_message="Candidate introduced hard prompt-eval safety failures."
            if regressions
            else None,
        )
        return self._persist_comparison_report(report)

    def load_report(self, eval_run_id: str) -> V2PromptEvalReport:
        path = validate_v2_data_path(
            self._data_dir,
            self._data_dir / "v2" / "prompt-evals" / eval_run_id / "report.json",
            operation="v2-prompt-eval-report-read",
        )
        if not path.exists():
            raise V2PromptEvalError(
                "prompt_eval_report_not_found",
                f"Prompt eval report not found: {eval_run_id}",
            )
        return V2PromptEvalReport.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_fixture(self, fixture_id: str) -> V2PromptEvalFixture:
        path = self._fixture_dir / f"{fixture_id}.json"
        if not path.exists():
            raise V2PromptEvalError(
                "prompt_eval_fixture_not_found",
                f"Prompt eval fixture not found: {fixture_id}",
            )
        try:
            return V2PromptEvalFixture.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, json.JSONDecodeError) as exc:
            raise V2PromptEvalError("prompt_eval_schema_failed", str(exc)) from exc

    def _profile(self, profile_id: str):
        try:
            return self._profiles.get(profile_id)
        except V2PromptProfileError as exc:
            raise V2PromptEvalError(exc.code, str(exc)) from exc

    def _build_fixture_context(
        self,
        fixture: V2PromptEvalFixture,
        profile_id: str,
        mode: V2PromptEvalMode,
    ) -> "_EvalContext":
        settings = replace(self._settings, agno_mock_mode=mode == "mock")
        profile = self._profile(profile_id)
        ad_payload = fixture.ad_request.model_dump(mode="json")
        if profile.prompt_suffix:
            ad_payload["prompt"] = f"{ad_payload['prompt']} {profile.prompt_suffix}".strip()
        request = WorkflowV2PlanFromPromptRequest(**ad_payload)
        constraints = extract_planning_constraints(request)
        request = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "planning_constraints": constraints.model_dump(mode="json"),
                }
            },
            deep=True,
        )
        descriptors = [
            descriptor.model_dump(mode="json") for descriptor in fixture.input_asset_descriptors
        ]
        from app.services.workflow_v2 import (
            WorkflowV2Error,
            WorkflowV2Service,
        )

        try:
            planned = WorkflowV2Service(settings).plan_from_prompt(request)
        except WorkflowV2Error as exc:
            raise V2PromptEvalError("prompt_eval_external_provider_blocked", str(exc)) from exc
        if isinstance(planned, WorkflowV2PlanningClarificationResponse):
            raise V2PromptEvalError(
                "prompt_eval_stage_failed",
                planned.message or "Workflow planning requires clarification.",
            )
        workflow = planned
        script_plan = V2ScriptPersistenceAdapter().normalize_metadata_plan(
            workflow.metadata.get("script_plan")
        )[0]
        expert_plan = V2ExpertBriefPlan.model_validate(workflow.metadata["expert_brief_plan"])
        _apply_eval_input_asset_descriptors(workflow, descriptors)
        _apply_profile_to_workflow(workflow, profile.specialist_prompt_suffix)
        V2WorkflowStore(self._data_dir).save_workflow(workflow)
        return _EvalContext(
            workflow=workflow,
            script_plan=script_plan,
            expert_plan=expert_plan,
            settings=settings,
            input_asset_descriptors=descriptors,
        )

    def _build_replay_context(self, workflow: WorkflowV2, profile_id: str) -> "_EvalContext":
        profile = self._profile(profile_id)
        script_payload = workflow.metadata.get("script_plan")
        expert_payload = workflow.metadata.get("expert_brief_plan")
        if not isinstance(script_payload, dict) or not isinstance(expert_payload, dict):
            raise V2PromptEvalError(
                "prompt_eval_replay_not_supported",
                "Workflow metadata does not include V2 script and expert brief plans.",
            )
        script_plan = V2ScriptPersistenceAdapter().normalize_metadata_plan(script_payload)[0]
        expert_plan = V2ExpertBriefPlan.model_validate(expert_payload)
        descriptors = workflow.metadata.get("input_asset_descriptors")
        workflow_copy = workflow.model_copy(deep=True)
        _apply_eval_input_asset_descriptors(
            workflow_copy,
            descriptors if isinstance(descriptors, list) else [],
        )
        _apply_profile_to_workflow(workflow_copy, profile.specialist_prompt_suffix)
        return _EvalContext(
            workflow=workflow_copy,
            script_plan=script_plan,
            expert_plan=expert_plan,
            settings=replace(self._settings, agno_mock_mode=True),
            input_asset_descriptors=descriptors if isinstance(descriptors, list) else [],
        )

    def _evaluate_context(
        self,
        *,
        context: "_EvalContext",
        profile_id: str,
        selected_stages: list[V2PromptEvalStage],
        expected_language: str | None,
    ) -> list[V2PromptEvalStageResult]:
        results: list[V2PromptEvalStageResult] = []
        profile = self._profile(profile_id)
        plan_records: list[_PlanRecord] | None = None
        for stage in selected_stages:
            if stage == "script_writer":
                results.append(
                    self._evaluate_script_writer(context, expected_language=expected_language)
                )
                continue
            if stage == "expert_brief":
                results.append(
                    self._evaluate_expert_brief(context, expected_language=expected_language)
                )
                continue
            if stage == "storyboard_detail_prompts":
                results.append(self._evaluate_storyboard_detail_prompts(context))
                continue
            if stage in {"specialist_prompts", "reference_bundle", "provider_payload"}:
                if plan_records is None:
                    plan_records = self._build_generation_plans(context, profile_id=profile_id)
                results.append(self._evaluate_plan_records(stage, plan_records, profile))
                continue
        return results

    def _evaluate_script_writer(
        self,
        context: "_EvalContext",
        *,
        expected_language: str | None,
    ) -> V2PromptEvalStageResult:
        failures = self._quality.evaluate_text(
            stage="script_writer",
            item_id="script-1",
            slot_id=None,
            slot_type="script",
            text=context.script_plan.script_text,
            expected_language=expected_language,
        )
        output = V2PromptEvalPromptOutput(
            item_id="script-1",
            slot_type="script",
            prompt=context.script_plan.script_text,
            materializer_mode=context.script_plan.materializer_mode,
        )
        return _stage_result("script_writer", failures=failures, outputs=[output], item_count=1)

    def _evaluate_expert_brief(
        self,
        context: "_EvalContext",
        *,
        expected_language: str | None,
    ) -> V2PromptEvalStageResult:
        prompts: dict[str, str] = {}
        outputs: list[V2PromptEvalPromptOutput] = []
        for product in context.expert_plan.product_briefs:
            prompts[f"product:{product.item_id}"] = product.item_prompt
            outputs.append(
                V2PromptEvalPromptOutput(
                    item_id=product.item_id,
                    slot_type="product",
                    prompt=product.item_prompt,
                )
            )
            outputs.extend(_asset_prompt_outputs(product.item_id, product.asset_prompts))
        for character in context.expert_plan.character_briefs:
            prompts[f"character:{character.item_id}"] = character.item_prompt
            outputs.append(
                V2PromptEvalPromptOutput(
                    item_id=character.item_id,
                    slot_type="character",
                    prompt=character.item_prompt,
                )
            )
            outputs.extend(_asset_prompt_outputs(character.item_id, character.asset_prompts))
        for scene in context.expert_plan.scene_briefs:
            prompts[f"scene:{scene.item_id}"] = scene.item_prompt
            outputs.append(
                V2PromptEvalPromptOutput(
                    item_id=scene.item_id,
                    slot_type="scene",
                    prompt=scene.item_prompt,
                )
            )
            outputs.extend(_asset_prompt_outputs(scene.item_id, scene.asset_prompts))
        if context.expert_plan.bgm_brief is not None:
            prompts[f"bgm:{context.expert_plan.bgm_brief.item_id}"] = (
                context.expert_plan.bgm_brief.item_prompt
            )
            outputs.append(
                V2PromptEvalPromptOutput(
                    item_id=context.expert_plan.bgm_brief.item_id,
                    slot_type="bgm",
                    prompt=context.expert_plan.bgm_brief.item_prompt,
                )
            )
        failures = self._quality.evaluate_expert_briefs(prompts)
        failures.extend(_specialist_quality_failures(context.expert_plan))
        for output in outputs:
            failures.extend(
                self._quality.evaluate_text(
                    stage="expert_brief",
                    item_id=output.item_id,
                    slot_id=None,
                    slot_type=output.slot_type,
                    text=output.prompt,
                    expected_language=expected_language,
                )
            )
        return _stage_result(
            "expert_brief",
            failures=failures,
            outputs=outputs,
            item_count=len(prompts),
            slot_count=len([output for output in outputs if output.slot_id]),
        )

    def _evaluate_storyboard_detail_prompts(
        self,
        context: "_EvalContext",
    ) -> V2PromptEvalStageResult:
        workflow = context.workflow.model_copy(deep=True)
        V2StoryboardDirector(context.settings).ensure_storyboard_shots(workflow)
        _seed_eval_storyboard_cell_assets(workflow, self._data_dir)
        failures: list[V2PromptEvalQualityFailure] = []
        outputs: list[V2PromptEvalPromptOutput] = []
        checked_slots = 0
        for item in _items(workflow, node_id="storyboard"):
            cell_prompts = [
                slot.slot_prompt
                for slot in item.slots
                if slot.slot_type.startswith("shot_cell_") and slot.slot_prompt
            ]
            failures.extend(
                self._quality.evaluate_storyboard_cells(
                    shot_id=item.shot_id or item.item_id,
                    cell_prompts=cell_prompts,
                )
            )
            for slot in item.slots:
                if (
                    not slot.slot_type.startswith("shot_cell_")
                    and slot.slot_type != "shot_video_segment"
                ):
                    continue
                checked_slots += 1
                outputs.append(
                    V2PromptEvalPromptOutput(
                        item_id=item.item_id,
                        slot_id=slot.slot_id,
                        slot_type=slot.slot_type,
                        media_type=slot.media_type,
                        prompt=slot.slot_prompt,
                    )
                )
                if slot.slot_type.startswith("shot_cell_"):
                    failures.extend(
                        self._quality.evaluate_text(
                            stage="storyboard_detail_prompts",
                            item_id=item.item_id,
                            slot_id=slot.slot_id,
                            slot_type=slot.slot_type,
                            text=slot.slot_prompt,
                        )
                    )
                else:
                    failures.extend(
                        self._quality.evaluate_storyboard_video_detail(
                            shot_id=item.shot_id or item.item_id,
                            prompt=slot.slot_prompt,
                            detail_prompts=item.detail_prompts,
                            selected_cell_asset_ids=list(slot.implicit_reference_ids),
                        )
                    )
        return _stage_result(
            "storyboard_detail_prompts",
            failures=failures,
            outputs=outputs,
            item_count=len(_items(workflow, node_id="storyboard")),
            slot_count=checked_slots,
        )

    def _build_generation_plans(
        self,
        context: "_EvalContext",
        *,
        profile_id: str,
    ) -> list["_PlanRecord"]:
        workflow = context.workflow.model_copy(deep=True)
        V2StoryboardDirector(context.settings).ensure_storyboard_shots(workflow)
        _seed_eval_main_image_assets(workflow, self._data_dir)
        _seed_eval_storyboard_cell_assets(workflow, self._data_dir)
        pipeline = V2GenerationPipeline(
            data_dir=self._data_dir,
            asset_store=V2AssetStoreService(self._data_dir),
            settings=context.settings,
        )
        profile = self._profile(profile_id)
        forbidden_terms = _prompt_eval_forbidden_terms(workflow)
        records: list[_PlanRecord] = []
        for item in _items(workflow):
            for slot in item.slots:
                if slot.status == "skipped":
                    continue
                try:
                    plan = pipeline.build_plan(workflow, item, slot, source_action="prompt_eval")
                except Exception as exc:  # noqa: BLE001 - stage result carries controlled error.
                    records.append(
                        _PlanRecord(
                            item=item,
                            slot=slot,
                            provider_payload={},
                            prompt=None,
                            materializer_mode=None,
                            error_code="prompt_eval_stage_failed",
                            error_message=str(exc),
                        )
                    )
                    continue
                payload = dict(plan.provider_payload)
                if forbidden_terms:
                    payload["prompt_eval_forbidden_terms"] = list(forbidden_terms)
                for injection in profile.provider_payload_injections:
                    if "provider_payload" in injection.stages:
                        payload[injection.key] = injection.value
                payload = _with_fake_provider_capture(payload, slot)
                records.append(
                    _PlanRecord(
                        item=item,
                        slot=slot,
                        provider_payload=payload,
                        prompt=plan.materialized_prompt.provider_prompt,
                        materializer_mode=plan.materialized_prompt.materializer_mode,
                        reference_asset_ids=list(plan.reference_asset_ids),
                    )
                )
        return records

    def _evaluate_plan_records(
        self,
        stage: V2PromptEvalStage,
        records: list["_PlanRecord"],
        profile: Any,
    ) -> V2PromptEvalStageResult:
        failures: list[V2PromptEvalQualityFailure] = []
        outputs: list[V2PromptEvalPromptOutput] = []
        warnings: list[str] = []
        for record in records:
            if record.error_code:
                warnings.append(f"{record.slot.slot_id}: {record.error_message}")
                failures.append(
                    V2PromptEvalQualityFailure(
                        failure_code="schema_validity",
                        message=record.error_message or "Prompt eval stage failed.",
                        stage=stage,
                        item_id=record.item.item_id,
                        slot_id=record.slot.slot_id,
                        slot_type=record.slot.slot_type,
                        gate="schema_validity",
                        hard_failure=True,
                    )
                )
                continue
            prompt = record.prompt or record.slot.slot_prompt
            if stage == "specialist_prompts":
                failures.extend(
                    self._quality.evaluate_text(
                        stage=stage,
                        item_id=record.item.item_id,
                        slot_id=record.slot.slot_id,
                        slot_type=record.slot.slot_type,
                        text=prompt,
                    )
                )
            elif stage == "reference_bundle":
                bundle = record.provider_payload.get("reference_bundle")
                payload = bundle if isinstance(bundle, dict) else {}
                failures.extend(
                    self._quality.evaluate_payload(
                        stage=stage,
                        item_id=record.item.item_id,
                        slot_id=record.slot.slot_id,
                        slot_type=record.slot.slot_type,
                        payload=payload,
                    )
                )
            elif stage == "provider_payload":
                failures.extend(
                    self._quality.evaluate_payload(
                        stage=stage,
                        item_id=record.item.item_id,
                        slot_id=record.slot.slot_id,
                        slot_type=record.slot.slot_type,
                        payload=record.provider_payload,
                    )
                )
            outputs.append(
                V2PromptEvalPromptOutput(
                    item_id=record.item.item_id,
                    slot_id=record.slot.slot_id,
                    slot_type=record.slot.slot_type,
                    media_type=record.slot.media_type,
                    prompt=record.slot.slot_prompt,
                    provider_prompt=prompt,
                    canonical_provider_prompt=_provider_prompt_from_payload(
                        record.provider_payload
                    ),
                    captured_provider_request_prompt=_captured_provider_prompt(
                        record.provider_payload
                    ),
                    provider_prompt_match=_provider_prompt_match(record.provider_payload),
                    materializer_mode=record.materializer_mode,
                    reference_asset_ids=list(record.reference_asset_ids),
                    prompt_isolation_audit=_prompt_isolation_audit(record.provider_payload),
                    prompt_registry_ref=_prompt_registry_ref(record.provider_payload),
                    prompt_lineage=_prompt_lineage(record.provider_payload),
                    provider_request_capture=_provider_request_capture(record.provider_payload),
                    provider_payload_summary=_provider_payload_summary(record.provider_payload),
                )
            )
        return _stage_result(
            stage,
            failures=failures,
            outputs=outputs,
            warnings=warnings,
            item_count=len({record.item.item_id for record in records}),
            slot_count=len(records),
        )

    def _persist_report(self, report: V2PromptEvalReport) -> V2PromptEvalReport:
        directory = self._report_dir(report.eval_run_id)
        report_path = directory / "report.json"
        trace_path = directory / "trace.json"
        report = report.model_copy(
            update={
                "report_path": report_path.relative_to(self._data_dir).as_posix(),
                "trace_path": trace_path.relative_to(self._data_dir).as_posix(),
            }
        )
        try:
            report = report.model_copy(
                update={
                    "provider_payload_captures": _collect_provider_payload_captures(report.stages),
                    "reference_ids": _collect_reference_ids(report.stages),
                    "prompt_lineage": _collect_prompt_lineage(report.stages),
                },
                deep=True,
            )
            _write_json_atomic(report_path, report.model_dump(mode="json"))
            _write_json_atomic(trace_path, _trace_payload(report))
        except OSError as exc:
            raise V2PromptEvalError("prompt_eval_report_write_failed", str(exc)) from exc
        return report

    def _persist_comparison_report(
        self,
        report: V2PromptEvalComparisonReport,
    ) -> V2PromptEvalComparisonReport:
        directory = self._report_dir(report.eval_run_id)
        report_path = directory / "report.json"
        trace_path = directory / "trace.json"
        report = report.model_copy(
            update={
                "report_path": report_path.relative_to(self._data_dir).as_posix(),
                "trace_path": trace_path.relative_to(self._data_dir).as_posix(),
            }
        )
        try:
            _write_json_atomic(report_path, report.model_dump(mode="json"))
            _write_json_atomic(trace_path, _comparison_trace_payload(report))
        except OSError as exc:
            raise V2PromptEvalError("prompt_eval_report_write_failed", str(exc)) from exc
        return report

    def _report_dir(self, eval_run_id: str) -> Path:
        directory = validate_v2_data_path(
            self._data_dir,
            self._data_dir / "v2" / "prompt-evals" / eval_run_id,
            operation="v2-prompt-eval-report-dir",
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory


class _EvalContext:
    def __init__(
        self,
        *,
        workflow: WorkflowV2,
        script_plan: V2ScriptPlanV2,
        expert_plan: V2ExpertBriefPlan,
        settings: Settings,
        input_asset_descriptors: list[dict[str, Any]],
    ) -> None:
        self.workflow = workflow
        self.script_plan = script_plan
        self.expert_plan = expert_plan
        self.settings = settings
        self.input_asset_descriptors = input_asset_descriptors


class _PlanRecord:
    def __init__(
        self,
        *,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        prompt: str | None,
        materializer_mode: str | None,
        reference_asset_ids: list[str] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.item = item
        self.slot = slot
        self.provider_payload = provider_payload
        self.prompt = prompt
        self.materializer_mode = materializer_mode
        self.reference_asset_ids = reference_asset_ids or []
        self.error_code = error_code
        self.error_message = error_message


def _default_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "v2_prompt_eval"


def _apply_profile_to_workflow(workflow: WorkflowV2, suffix: str | None) -> None:
    if not suffix:
        return
    for item in _items(workflow):
        if item.item_prompt:
            item.item_prompt = f"{item.item_prompt} {suffix}".strip()
        if item.user_prompt:
            item.user_prompt = f"{item.user_prompt} {suffix}".strip()
        elif item.system_suggested_prompt:
            item.system_suggested_prompt = f"{item.system_suggested_prompt} {suffix}".strip()
        for slot in item.slots:
            if slot.slot_prompt:
                slot.slot_prompt = f"{slot.slot_prompt} {suffix}".strip()
            if slot.user_prompt:
                slot.user_prompt = f"{slot.user_prompt} {suffix}".strip()
            elif slot.system_suggested_prompt:
                slot.system_suggested_prompt = f"{slot.system_suggested_prompt} {suffix}".strip()


def _apply_eval_input_asset_descriptors(
    workflow: WorkflowV2,
    descriptors: list[dict[str, Any]],
) -> None:
    asset_ids = [
        str(descriptor.get("asset_id") or "").strip()
        for descriptor in descriptors
        if _is_product_reference_descriptor(descriptor)
        and str(descriptor.get("asset_id") or "").strip()
    ]
    asset_ids = list(dict.fromkeys(asset_ids))
    if not asset_ids:
        return
    workflow.metadata["input_asset_descriptors"] = list(descriptors)
    for item in _items(workflow, node_id="product-generation"):
        existing_item_refs = [
            str(asset_id)
            for asset_id in item.metadata.get("explicit_reference_asset_ids", [])
            if str(asset_id)
        ]
        item.metadata["explicit_reference_asset_ids"] = list(
            dict.fromkeys([*existing_item_refs, *asset_ids])
        )
        for slot in item.slots:
            if not slot.slot_type.startswith("product_"):
                continue
            slot.explicit_reference_ids = list(
                dict.fromkeys([*slot.explicit_reference_ids, *asset_ids])
            )


def _is_product_reference_descriptor(descriptor: dict[str, Any]) -> bool:
    values = [
        descriptor.get("semantic_type"),
        descriptor.get("reference_role"),
        descriptor.get("display_name"),
        descriptor.get("metadata", {}).get("semantic_type")
        if isinstance(descriptor.get("metadata"), dict)
        else None,
        descriptor.get("metadata", {}).get("entity_type")
        if isinstance(descriptor.get("metadata"), dict)
        else None,
    ]
    text = " ".join(str(value).lower() for value in values if value)
    return any(term in text for term in ("product", "packaging", "brand", "商品", "产品"))


def _prompt_eval_forbidden_terms(workflow: WorkflowV2) -> list[str]:
    request = workflow.metadata.get("request")
    metadata = request.get("metadata") if isinstance(request, dict) else None
    if not isinstance(metadata, dict):
        return []
    terms = metadata.get("prompt_eval_forbidden_terms")
    if not isinstance(terms, list):
        return []
    return list(dict.fromkeys(str(term).strip() for term in terms if str(term).strip()))


def _items(workflow: WorkflowV2, *, node_id: str | None = None) -> list[WorkflowItemV2]:
    items: list[WorkflowItemV2] = []
    for node in workflow.nodes:
        if node_id is not None and node.node_id != node_id:
            continue
        items.extend(node.items)
    return items


def _asset_prompt_outputs(
    item_id: str,
    asset_prompts: dict[str, str],
) -> list[V2PromptEvalPromptOutput]:
    return [
        V2PromptEvalPromptOutput(
            item_id=item_id,
            slot_id=f"{item_id}:{slot_type}",
            slot_type=slot_type,
            prompt=prompt,
        )
        for slot_type, prompt in asset_prompts.items()
        if str(prompt).strip()
    ]


def _specialist_quality_failures(
    expert_plan: V2ExpertBriefPlan,
) -> list[V2PromptEvalQualityFailure]:
    failures: list[V2PromptEvalQualityFailure] = []
    for violation in V2SpecialistAssetPromptQualityValidator().evaluate_plan(expert_plan):
        failures.append(
            V2PromptEvalQualityFailure(
                failure_code=violation.code,
                message=violation.message,
                stage="expert_brief",
                item_id=violation.item_id,
                slot_id=f"{violation.item_id}:{violation.slot_type}",
                slot_type=violation.slot_type,
                gate="specialist_asset_prompt_quality",
                hard_failure=True,
                evidence=violation.repair_instruction,
            )
        )
    return failures


def _seed_eval_storyboard_cell_assets(workflow: WorkflowV2, data_dir: Path) -> None:
    asset_store = V2AssetStoreService(data_dir)
    for item in _items(workflow, node_id="storyboard"):
        cell_asset_ids: list[str] = []
        for slot in item.slots:
            if not slot.slot_type.startswith("shot_cell_"):
                continue
            asset_id = slot.selected_asset_id or f"eval-{item.item_id}-{slot.slot_type}-asset"
            version_id = slot.selected_version_id or f"ver_{asset_id}"
            file_path = (
                Path("assets")
                / "generated"
                / workflow.workflow_id
                / "prompt-eval"
                / item.item_id
                / f"{slot.slot_type}.png"
            )
            absolute_path = data_dir / file_path
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            if not absolute_path.exists():
                absolute_path.write_bytes(b"prompt-eval-storyboard-cell")
            asset_store.save_asset_version(
                WorkflowAssetVersionV2(
                    asset_id=asset_id,
                    version_id=version_id,
                    media_type="image",
                    source_type="generated",
                    file_path=file_path.as_posix(),
                    public_url=f"/media/{file_path.as_posix()}",
                    workflow_id=workflow.workflow_id,
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    semantic_type="shot_cell_image",
                    created_by="v2-prompt-eval",
                    metadata={"prompt_eval_synthetic_asset": True},
                )
            )
            slot.selected_asset_id = asset_id
            slot.selected_version_id = version_id
            slot.current_working_asset_id = asset_id
            slot.current_working_version_id = version_id
            slot.status = "completed"
            slot.metadata["prompt_eval_synthetic_asset"] = True
            cell_asset_ids.append(asset_id)
        if not cell_asset_ids:
            continue
        for slot in item.slots:
            if slot.slot_type != "shot_video_segment":
                continue
            slot.implicit_reference_ids = list(cell_asset_ids)
            slot.metadata["prompt_eval_selected_cell_asset_ids"] = list(cell_asset_ids)


def _seed_eval_main_image_assets(workflow: WorkflowV2, data_dir: Path) -> None:
    asset_store = V2AssetStoreService(data_dir)
    for item in _items(workflow):
        if item.item_type not in {"product", "character", "scene"}:
            continue
        main_slot_type = {
            "product": "product_main_image",
            "character": "character_main_image",
            "scene": "scene_main_image",
        }[item.item_type]
        for slot in item.slots:
            if slot.slot_type != main_slot_type:
                continue
            asset_id = slot.selected_asset_id or f"eval-{item.item_id}-{slot.slot_type}-asset"
            version_id = slot.selected_version_id or f"ver_{asset_id}"
            file_path = (
                Path("assets")
                / "generated"
                / workflow.workflow_id
                / "prompt-eval"
                / item.item_id
                / f"{slot.slot_type}.png"
            )
            absolute_path = data_dir / file_path
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            if not absolute_path.exists():
                absolute_path.write_bytes(b"prompt-eval-main-image")
            asset_store.save_asset_version(
                WorkflowAssetVersionV2(
                    asset_id=asset_id,
                    version_id=version_id,
                    media_type="image",
                    source_type="generated",
                    file_path=file_path.as_posix(),
                    public_url=f"/media/{file_path.as_posix()}",
                    workflow_id=workflow.workflow_id,
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    semantic_type=slot.slot_type,
                    created_by="v2-prompt-eval",
                    metadata={
                        "prompt_eval_synthetic_asset": True,
                        "prompt_summary": item.item_prompt or item.display_name,
                        "provider_prompt": slot.slot_prompt,
                    },
                )
            )
            slot.selected_asset_id = asset_id
            slot.selected_version_id = version_id
            slot.current_working_asset_id = asset_id
            slot.current_working_version_id = version_id
            slot.status = "completed"
            slot.metadata["prompt_eval_synthetic_asset"] = True


def _normalize_stages(stages: list[V2PromptEvalStage]) -> list[V2PromptEvalStage]:
    if "all" in stages:
        return list(PROMPT_EVAL_STAGES)
    return [stage for stage in stages if stage != "all"]


def _stage_result(
    stage: V2PromptEvalStage,
    *,
    failures: list[V2PromptEvalQualityFailure],
    outputs: list[V2PromptEvalPromptOutput],
    warnings: list[str] | None = None,
    item_count: int = 0,
    slot_count: int = 0,
) -> V2PromptEvalStageResult:
    return V2PromptEvalStageResult(
        stage=stage,
        status=_status_from_failures(failures),
        checked_item_count=item_count,
        checked_slot_count=slot_count,
        outputs=outputs,
        failures=failures,
        warnings=warnings or [],
    )


def _status_from_failures(failures: list[V2PromptEvalQualityFailure]) -> V2PromptEvalStatus:
    if any(failure.hard_failure for failure in failures):
        return "failed"
    if failures:
        return "partial_failed"
    return "passed"


def _report_status(stage_results: list[V2PromptEvalStageResult]) -> V2PromptEvalStatus:
    if any(stage.status == "error" for stage in stage_results):
        return "error"
    if any(stage.status == "failed" for stage in stage_results):
        return "failed"
    if any(stage.status == "partial_failed" for stage in stage_results):
        return "partial_failed"
    return "passed"


def _collect_failures(
    stage_results: list[V2PromptEvalStageResult],
) -> list[V2PromptEvalQualityFailure]:
    return [failure for stage in stage_results for failure in stage.failures]


def _collect_provider_payload_captures(
    stage_results: list[V2PromptEvalStageResult],
) -> list[dict[str, Any]]:
    captures: list[dict[str, Any]] = []
    for stage in stage_results:
        if stage.stage != "provider_payload":
            continue
        for output in stage.outputs:
            if output.provider_request_capture:
                captures.append(
                    {
                        "item_id": output.item_id,
                        "slot_id": output.slot_id,
                        "slot_type": output.slot_type,
                        **output.provider_request_capture,
                    }
                )
    return captures


def _collect_reference_ids(stage_results: list[V2PromptEvalStageResult]) -> list[str]:
    reference_ids: list[str] = []
    for stage in stage_results:
        for output in stage.outputs:
            reference_ids.extend(str(asset_id) for asset_id in output.reference_asset_ids)
    return list(dict.fromkeys(asset_id for asset_id in reference_ids if asset_id))


def _collect_prompt_lineage(stage_results: list[V2PromptEvalStageResult]) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stage in stage_results:
        for output in stage.outputs:
            if not output.prompt_lineage:
                continue
            key = "|".join(
                str(output.prompt_lineage.get(field) or "")
                for field in ("slot_id", "prompt_hash", "render_context_hash")
            )
            if key in seen:
                continue
            seen.add(key)
            lineage.append(output.prompt_lineage)
    return lineage


def _hard_regressions(
    baseline_reports: list[V2PromptEvalReport],
    candidate_reports: list[V2PromptEvalReport],
) -> list[V2PromptEvalQualityFailure]:
    baseline_keys = {
        _failure_key(report, failure)
        for report in baseline_reports
        for failure in report.failures
        if failure.hard_failure
    }
    regressions: list[V2PromptEvalQualityFailure] = []
    for report in candidate_reports:
        for failure in report.failures:
            if failure.hard_failure and _failure_key(report, failure) not in baseline_keys:
                regressions.append(failure)
    return regressions


def _failure_key(
    report: V2PromptEvalReport,
    failure: V2PromptEvalQualityFailure,
) -> tuple[str | None, str, str | None, str | None]:
    return (report.fixture_id, failure.failure_code, failure.slot_id, failure.evidence)


def _provider_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    canonical = payload.get("canonical_provider_payload")
    capture = _provider_request_capture(payload)
    prompt_ref = _prompt_registry_ref(payload)
    prompt_lineage = _prompt_lineage(payload)
    prompt_content_profile = _prompt_content_profile(payload)
    return {
        "keys": sorted(str(key) for key in payload if not _is_sensitive_key(str(key))),
        "slot_type": payload.get("slot_type")
        or (canonical.get("slot_type") if isinstance(canonical, dict) else None),
        "media_type": payload.get("media_type")
        or (canonical.get("media_type") if isinstance(canonical, dict) else None),
        "reference_asset_count": len(payload.get("reference_asset_ids") or []),
        "has_reference_bundle": isinstance(payload.get("reference_bundle"), dict),
        "provider_prompt_chars": len(str(payload.get("provider_prompt") or "")),
        "canonical_provider_prompt_chars": len(_provider_prompt_from_payload(payload)),
        "captured_provider_request_prompt_chars": len(
            str(capture.get("actual_provider_request_prompt") or "")
        ),
        "provider_prompt_match": capture.get("prompt_match"),
        "has_prompt_isolation_audit": bool(_prompt_isolation_audit(payload)),
        "has_prompt_registry_ref": bool(prompt_ref),
        "prompt_id": prompt_ref.get("prompt_id"),
        "prompt_version": prompt_ref.get("prompt_version"),
        "prompt_owner": prompt_ref.get("owner") or prompt_lineage.get("owner"),
        "path_kind": prompt_lineage.get("path_kind"),
        "prompt_content_profile": prompt_content_profile,
    }


def _with_fake_provider_capture(
    payload: dict[str, Any],
    slot: WorkflowSlotV2,
) -> dict[str, Any]:
    enriched = dict(payload)
    canonical_prompt = _provider_prompt_from_payload(enriched)
    existing_capture = enriched.get("provider_request_capture")
    capture = dict(existing_capture) if isinstance(existing_capture, dict) else {}
    actual_prompt = (
        capture.get("actual_provider_request_prompt")
        or enriched.get("actual_provider_request_prompt")
        or enriched.get("captured_provider_request_prompt")
        or canonical_prompt
    )
    actual_prompt = str(actual_prompt or "").strip()
    prompt_match = canonical_prompt.strip() == actual_prompt if canonical_prompt else None
    capture.update(
        {
            "provider": str(slot.provider_params.get("provider") or "fake_provider"),
            "slot_id": slot.slot_id,
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "canonical_provider_prompt": canonical_prompt,
            "actual_provider_request_prompt": actual_prompt,
            "prompt_match": prompt_match,
            "reference_asset_ids": list(enriched.get("reference_asset_ids") or []),
            "prompt_source": "fake_provider_capture",
        }
    )
    enriched["provider_request_capture"] = capture
    enriched["prompt_eval_capture_required"] = True
    enriched = _sync_synthetic_eval_reference_audit(enriched)
    return enriched


def _provider_prompt_from_payload(payload: dict[str, Any]) -> str:
    prompt = payload.get("provider_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    canonical = payload.get("canonical_provider_payload")
    if isinstance(canonical, dict):
        prompt = canonical.get("provider_prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
    return ""


def _provider_request_capture(payload: dict[str, Any]) -> dict[str, Any]:
    capture = payload.get("provider_request_capture")
    return dict(capture) if isinstance(capture, dict) else {}


def _captured_provider_prompt(payload: dict[str, Any]) -> str | None:
    capture = _provider_request_capture(payload)
    prompt = capture.get("actual_provider_request_prompt")
    return str(prompt).strip() if isinstance(prompt, str) and prompt.strip() else None


def _provider_prompt_match(payload: dict[str, Any]) -> bool | None:
    capture = _provider_request_capture(payload)
    value = capture.get("prompt_match")
    return value if isinstance(value, bool) else None


def _prompt_isolation_audit(payload: dict[str, Any]) -> dict[str, Any]:
    audit = payload.get("prompt_isolation_audit")
    return dict(audit) if isinstance(audit, dict) else {}


def _prompt_registry_ref(payload: dict[str, Any]) -> dict[str, Any]:
    ref = payload.get("prompt_registry_ref")
    if isinstance(ref, dict):
        return dict(ref)
    lineage = payload.get("prompt_lineage")
    if isinstance(lineage, dict) and isinstance(lineage.get("prompt_registry_ref"), dict):
        return dict(lineage["prompt_registry_ref"])
    return {}


def _prompt_lineage(payload: dict[str, Any]) -> dict[str, Any]:
    lineage = payload.get("prompt_lineage")
    return dict(lineage) if isinstance(lineage, dict) else {}


def _prompt_content_profile(payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("prompt_content_profile")
    if isinstance(profile, dict):
        return dict(profile)
    contract = payload.get("provider_prompt_contract")
    if isinstance(contract, dict) and isinstance(contract.get("prompt_content_profile"), dict):
        return dict(contract["prompt_content_profile"])
    return {}


def _sync_synthetic_eval_reference_audit(payload: dict[str, Any]) -> dict[str, Any]:
    reference_ids = [
        str(asset_id)
        for asset_id in payload.get("reference_asset_ids", [])
        if str(asset_id).startswith("eval-")
    ]
    if not reference_ids:
        return payload
    audit = payload.get("reference_audit")
    if not isinstance(audit, dict):
        return payload
    synced = dict(payload)
    synced_audit = dict(audit)
    for field_name in (
        "requested_reference_asset_ids",
        "required_reference_asset_ids",
        "submitted_reference_asset_ids",
        "allowed_reference_asset_ids",
    ):
        existing = [str(asset_id) for asset_id in synced_audit.get(field_name, [])]
        synced_audit[field_name] = list(dict.fromkeys([*existing, *reference_ids]))
    if not isinstance(synced_audit.get("provider_capability_snapshot"), dict):
        synced_audit["provider_capability_snapshot"] = {}
    if not synced_audit["provider_capability_snapshot"]:
        synced_audit["provider_capability_snapshot"] = {
            "provider": "fake_provider",
            "max_reference_assets": max(8, len(reference_ids)),
        }
    synced["reference_audit"] = synced_audit
    return synced


def _is_sensitive_key(value: str) -> bool:
    normalized = value.lower()
    return any(term in normalized for term in ("api_key", "secret", "token", "password"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _trace_payload(report: V2PromptEvalReport) -> dict[str, Any]:
    return {
        "eval_run_id": report.eval_run_id,
        "fixture_id": report.fixture_id,
        "workflow_id": report.workflow_id,
        "profile_id": report.profile_id,
        "status": report.status,
        "selected_stages": report.selected_stages,
        "failures": [failure.model_dump(mode="json") for failure in report.failures],
    }


def _comparison_trace_payload(report: V2PromptEvalComparisonReport) -> dict[str, Any]:
    return {
        "eval_run_id": report.eval_run_id,
        "baseline_profile_id": report.baseline_profile_id,
        "candidate_profile_id": report.candidate_profile_id,
        "status": report.status,
        "selected_stages": report.selected_stages,
        "regressions": [failure.model_dump(mode="json") for failure in report.regressions],
    }


def _new_eval_run_id() -> str:
    return f"peval_{uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
