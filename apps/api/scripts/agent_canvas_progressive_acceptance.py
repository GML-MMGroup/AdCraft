"""Deterministic contracts for progressive Agent Canvas acceptance evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


AcceptanceTarget = Literal["video_draft", "ready_video", "final_export"]
AcceptanceStatus = Literal["pass", "fail"]
CreativeReviewStatus = Literal["pending", "pass", "needs_improvement"]

ACCEPTANCE_TARGET_INCOMPLETE = "acceptance_target_incomplete"
ACCEPTANCE_NODE_ROLE_MISMATCH = "acceptance_node_role_mismatch"
ACCEPTANCE_PROMPT_ROLE_MISMATCH = "acceptance_prompt_role_mismatch"
ACCEPTANCE_BINDING_MISSING = "acceptance_binding_missing"
ACCEPTANCE_RESOLVED_INPUT_MISSING = "acceptance_resolved_input_missing"
ACCEPTANCE_PROVIDER_REFERENCE_MISSING = "acceptance_provider_reference_missing"
ACCEPTANCE_PROVIDER_TERMINAL_EVENT_MISSING = "acceptance_provider_terminal_event_missing"
ACCEPTANCE_MEDIA_PARAMETER_MISMATCH = "acceptance_media_parameter_mismatch"
ACCEPTANCE_OUTPUT_ASSET_MISSING = "acceptance_output_asset_missing"
ACCEPTANCE_GUIDANCE_INCOMPLETE = "acceptance_guidance_incomplete"
ACCEPTANCE_UNEXPECTED_CONTINUATION = "acceptance_unexpected_continuation"
ACCEPTANCE_CREATIVE_REVIEW_PENDING = "acceptance_creative_review_pending"
ACCEPTANCE_ATTEMPT_LINEAGE_INVALID = "acceptance_attempt_lineage_invalid"


class _AcceptanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcceptanceRelationshipV2(_AcceptanceModel):
    source_role: str = Field(min_length=1)
    target_role: str = Field(min_length=1)
    input_role: str = Field(min_length=1)
    require_provider_delivery: bool = True
    provider_supports_reference: bool = True


class ProgressiveAcceptanceScenarioV2(_AcceptanceModel):
    schema_version: Literal["2"] = "2"
    scenario_name: str = "standard"
    target: AcceptanceTarget
    require_guidance_complete: bool
    expected_creative_roles: tuple[str, ...]
    expected_role_counts: dict[str, int] = Field(default_factory=dict)
    required_relationships: tuple[AcceptanceRelationshipV2, ...] = ()
    requested_parameters: dict[str, Any] = Field(default_factory=dict)
    audio_policy: Literal["full", "no_bgm", "silent"] = "full"


class AcceptanceNodeEvidenceV2(_AcceptanceModel):
    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    creative_role: str = Field(min_length=1)
    status: str = Field(min_length=1)
    generation_prompt: str = ""
    structured_content: dict[str, Any] = Field(default_factory=dict)
    output_asset_id: str | None = None
    output_version_id: str | None = None
    materialization_id: str | None = None
    node_run_id: str | None = None
    execution_id: str | None = None
    provider_task_id: str | None = None
    provider: str | None = None
    model_ref: str | None = None
    provider_terminal: bool = False
    run_input_binding_ids: tuple[str, ...] = ()
    submitted_reference_asset_ids: tuple[str, ...] = ()
    dropped_references: tuple[dict[str, Any], ...] = ()
    requested_parameters: dict[str, Any] = Field(default_factory=dict)
    effective_parameters: dict[str, Any] = Field(default_factory=dict)
    actual_media_facts: dict[str, Any] = Field(default_factory=dict)


class AcceptanceBindingEvidenceV2(_AcceptanceModel):
    binding_id: str = Field(min_length=1)
    source_node_id: str | None = None
    source_asset_id: str | None = None
    target_node_id: str = Field(min_length=1)
    input_role: str = Field(min_length=1)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> "AcceptanceBindingEvidenceV2":
        if bool(self.source_node_id) == bool(self.source_asset_id):
            raise ValueError("A Binding must identify exactly one source.")
        return self


class AcceptanceAssetEvidenceV2(_AcceptanceModel):
    asset_id: str = Field(min_length=1)
    version_id: str | None = None
    media_type: str = Field(min_length=1)
    readable: bool
    checksum: str | None = None
    media_url: str | None = None


class AcceptanceEvidenceV2(_AcceptanceModel):
    workflow_id: str = Field(min_length=1)
    project_id: str | None = None
    guidance_status: str | None = None
    active_proposal_id: str | None = None
    open_continuation_ids: tuple[str, ...] = ()
    nodes: tuple[AcceptanceNodeEvidenceV2, ...]
    bindings: tuple[AcceptanceBindingEvidenceV2, ...] = ()
    assets: tuple[AcceptanceAssetEvidenceV2, ...] = ()
    agent_runs: tuple[dict[str, Any], ...] = ()
    materializations: tuple[dict[str, Any], ...] = ()
    executions: tuple[dict[str, Any], ...] = ()
    provider_tasks: tuple[dict[str, Any], ...] = ()
    event_cursor: int = Field(default=0, ge=0)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ProgressiveMediaProbeCache:
    """Probe each unique canonical Asset version at most once per attempt."""

    def __init__(self, probe: Callable[[str, str], dict[str, Any]]) -> None:
        self._probe = probe
        self._facts: dict[tuple[str, str | None], dict[str, Any]] = {}

    def probe(self, asset: dict[str, Any]) -> dict[str, Any]:
        identity = (str(asset.get("asset_id") or ""), asset.get("version_id"))
        if identity not in self._facts:
            url = str(asset.get("media_url") or "")
            media_type = str(asset.get("media_type") or "unknown")
            self._facts[identity] = self._probe(url, media_type) if url else {}
        return self._facts[identity]


class ProgressiveAcceptanceEvidenceCollector:
    """Project existing public payloads into a canonical read-only snapshot."""

    def collect(
        self,
        *,
        workflow: dict[str, Any],
        timeline: dict[str, Any],
        runtime: dict[str, Any] | None = None,
        events: dict[str, Any] | None = None,
        assets: dict[str, Any] | None = None,
        media_probe_cache: ProgressiveMediaProbeCache | None = None,
    ) -> AcceptanceEvidenceV2:
        runtime = runtime or {}
        events = events or {}
        assets = assets or {}
        event_items = tuple(item for item in events.get("items") or [] if isinstance(item, dict))
        runtime_nodes = runtime.get("node_runtime") or {}
        asset_items = tuple(
            {
                **item,
                **(media_probe_cache.probe(item) if media_probe_cache is not None else {}),
            }
            for item in assets.get("assets") or []
            if isinstance(item, dict)
        )
        assets_by_id = {
            str(item.get("asset_id")): item for item in asset_items if item.get("asset_id")
        }
        nodes = tuple(
            self._node(
                item,
                runtime_nodes.get(str(item.get("node_id"))) or {},
                event_items,
                assets_by_id,
            )
            for item in workflow.get("nodes") or []
            if isinstance(item, dict)
        )
        bindings = tuple(
            AcceptanceBindingEvidenceV2(
                binding_id=str(item.get("binding_id") or ""),
                source_node_id=(item.get("source") or {}).get("source_node_id"),
                source_asset_id=(item.get("source") or {}).get("source_asset_id"),
                target_node_id=str(item.get("target_node_id") or ""),
                input_role=str(item.get("input_role") or ""),
                enabled=item.get("enabled") is not False,
            )
            for item in workflow.get("bindings") or []
            if isinstance(item, dict)
        )
        guidance = timeline.get("guidance_session") or {}
        continuations = tuple(
            str(item.get("continuation_id"))
            for item in timeline.get("continuations") or []
            if isinstance(item, dict)
            and item.get("continuation_id")
            and item.get("status") in {"queued", "leased", "running", "waiting"}
        )
        return AcceptanceEvidenceV2(
            workflow_id=str(workflow.get("workflow_id") or ""),
            project_id=workflow.get("project_id"),
            guidance_status=_guidance_status(guidance),
            active_proposal_id=guidance.get("active_proposal_id"),
            open_continuation_ids=continuations,
            nodes=nodes,
            bindings=bindings,
            assets=tuple(self._asset(item) for item in asset_items),
            agent_runs=_event_payloads(event_items, prefix="agent_run_"),
            materializations=_event_payloads(event_items, prefix="proposal_materialization_"),
            executions=_event_payloads(event_items, prefix="execution_"),
            provider_tasks=_event_payloads(event_items, prefix="provider_task_"),
            event_cursor=int(events.get("next_cursor") or runtime.get("events_cursor") or 0),
        )

    @staticmethod
    def _node(
        item: dict[str, Any],
        runtime: dict[str, Any],
        events: tuple[dict[str, Any], ...],
        assets_by_id: dict[str, dict[str, Any]],
    ) -> AcceptanceNodeEvidenceV2:
        node_id = str(item.get("node_id") or "")
        node_events = tuple(event for event in events if str(event.get("node_id") or "") == node_id)
        payloads = tuple(event.get("payload") or {} for event in node_events)
        provider_event = next(
            (
                event
                for event in reversed(node_events)
                if str(event.get("event_type") or "").startswith("provider_task_")
            ),
            None,
        )
        provider_payload = (provider_event or {}).get("payload") or {}
        output_asset_id = item.get("output_asset_id")
        asset = assets_by_id.get(str(output_asset_id or ""), {})
        provider_task_id = provider_payload.get("provider_task_id") or runtime.get(
            "provider_task_id"
        )
        structured_content = item.get("structured_content") or {}
        manifest = structured_content.get("manifest") or {}
        manifest_binding_ids = tuple(
            str(entry.get("binding_id"))
            for key in ("video_entries", "audio_entries")
            for entry in manifest.get(key) or []
            if isinstance(entry, dict)
            and entry.get("binding_id")
            and entry.get("enabled") is not False
        )
        return AcceptanceNodeEvidenceV2(
            node_id=node_id,
            node_type=str(item.get("node_type") or ""),
            creative_role=str(item.get("creative_role") or ""),
            status=str(item.get("status") or ""),
            generation_prompt=str(item.get("generation_prompt") or ""),
            structured_content=structured_content,
            output_asset_id=output_asset_id,
            output_version_id=item.get("output_version_id") or asset.get("version_id"),
            materialization_id=_last_scalar(payloads, "materialization_id"),
            node_run_id=_last_scalar(payloads, "node_run_id", "run_id"),
            execution_id=runtime.get("execution_id") or _last_scalar(payloads, "execution_id"),
            provider_task_id=provider_task_id,
            provider=provider_payload.get("provider") or asset.get("provider"),
            model_ref=provider_payload.get("model_ref")
            or provider_payload.get("model_id")
            or asset.get("model_ref")
            or asset.get("model_id"),
            provider_terminal=bool(
                provider_event
                and str(provider_event.get("event_type") or "")
                in {"provider_task_completed", "provider_task_succeeded"}
                or provider_task_id
                and item.get("status") == "ready"
                and output_asset_id
                and asset.get("media_url")
            ),
            run_input_binding_ids=_merge_id_groups(
                _merged_ids(payloads, "run_input_binding_ids", "binding_ids"),
                _media_input_ids(payloads, "binding_id"),
                manifest_binding_ids,
            ),
            submitted_reference_asset_ids=_merge_id_groups(
                _merged_ids(
                    payloads,
                    "submitted_reference_asset_ids",
                    "reference_asset_ids",
                    "input_asset_ids",
                ),
                _media_input_ids(payloads, "asset_id", require_transport=True),
            ),
            dropped_references=tuple(
                dropped
                for payload in payloads
                for dropped in payload.get("dropped_references") or []
                if isinstance(dropped, dict)
            ),
            requested_parameters=item.get("parameters") or {},
            effective_parameters=runtime.get("effective_parameters")
            or _last_mapping(payloads, "effective_parameters"),
            actual_media_facts={
                key: asset[key]
                for key in (
                    "width",
                    "height",
                    "duration_seconds",
                    "has_audio",
                    "video_codec",
                    "audio_codec",
                )
                if asset.get(key) is not None
            },
        )

    @staticmethod
    def _asset(item: dict[str, Any]) -> AcceptanceAssetEvidenceV2:
        return AcceptanceAssetEvidenceV2(
            asset_id=str(item.get("asset_id") or ""),
            version_id=item.get("version_id") or item.get("selected_version_id"),
            media_type=str(item.get("media_type") or "unknown"),
            readable=bool(item.get("media_url"))
            and item.get("status") in {None, "ready", "active"},
            checksum=item.get("sha256") or item.get("checksum"),
            media_url=item.get("media_url"),
        )


class AcceptanceCheckV2(_AcceptanceModel):
    code: str = Field(min_length=1)
    status: AcceptanceStatus
    message: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class CreativeReviewV2(_AcceptanceModel):
    status: CreativeReviewStatus = "pending"
    observations: tuple[str, ...] = ()
    reviewed_at: datetime | None = None


class ProgressiveAcceptanceReportV2(_AcceptanceModel):
    schema_version: Literal["2"] = "2"
    acceptance_run_id: str = Field(min_length=1)
    parent_run_id: str | None = None
    resume_count: int = Field(default=0, ge=0)
    attempt_elapsed_seconds: float = Field(default=0, ge=0)
    cumulative_elapsed_seconds: float = Field(default=0, ge=0)
    target: AcceptanceTarget
    technical_checks: tuple[AcceptanceCheckV2, ...]
    technical_verdict: AcceptanceStatus
    creative_review: CreativeReviewV2
    evidence: AcceptanceEvidenceV2
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


_ROLE_NODE_TYPES: dict[str, set[str]] = {
    "product": {"image"},
    "character": {"image"},
    "scene": {"image"},
    "storyboard_sequence": {"image"},
    "storyboard_video": {"video"},
    "bgm": {"audio"},
    "editing": {"editing"},
}


class ProgressiveAcceptanceEvaluator:
    """Evaluate a read-only evidence snapshot against one explicit scenario."""

    def evaluate(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        evidence: AcceptanceEvidenceV2,
        *,
        creative_review: CreativeReviewV2,
        acceptance_run_id: str | None = None,
        parent_run_id: str | None = None,
        attempt_elapsed_seconds: float = 0,
    ) -> ProgressiveAcceptanceReportV2:
        checks: list[AcceptanceCheckV2] = []
        nodes_by_role = {node.creative_role: node for node in evidence.nodes}
        assets_by_id = {asset.asset_id: asset for asset in evidence.assets}

        self._check_expected_nodes(scenario, nodes_by_role, evidence.nodes, checks)
        self._check_target(scenario, nodes_by_role, assets_by_id, evidence, checks)
        self._check_relationships(scenario, nodes_by_role, evidence, checks)
        self._check_prompts(nodes_by_role, checks)
        self._check_guidance(scenario, evidence, checks)
        self._check_media_parameters(scenario, nodes_by_role, checks)

        verdict: AcceptanceStatus = (
            "fail" if any(check.status == "fail" for check in checks) else "pass"
        )
        return ProgressiveAcceptanceReportV2(
            acceptance_run_id=acceptance_run_id or f"acceptance_{uuid4().hex}",
            parent_run_id=parent_run_id,
            attempt_elapsed_seconds=round(attempt_elapsed_seconds, 3),
            cumulative_elapsed_seconds=round(attempt_elapsed_seconds, 3),
            target=scenario.target,
            technical_checks=tuple(checks),
            technical_verdict=verdict,
            creative_review=creative_review,
            evidence=evidence,
        )

    @staticmethod
    def _pass(code: str, message: str, *evidence_ids: str) -> AcceptanceCheckV2:
        return AcceptanceCheckV2(
            code=code,
            status="pass",
            message=message,
            evidence_ids=tuple(item for item in evidence_ids if item),
        )

    @staticmethod
    def _fail(code: str, message: str, *evidence_ids: str) -> AcceptanceCheckV2:
        return AcceptanceCheckV2(
            code=code,
            status="fail",
            message=message,
            evidence_ids=tuple(item for item in evidence_ids if item),
        )

    def _check_expected_nodes(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        nodes_by_role: dict[str, AcceptanceNodeEvidenceV2],
        nodes: tuple[AcceptanceNodeEvidenceV2, ...],
        checks: list[AcceptanceCheckV2],
    ) -> None:
        for role in scenario.expected_creative_roles:
            node = nodes_by_role.get(role)
            allowed_types = _ROLE_NODE_TYPES.get(role)
            if node is None or (allowed_types is not None and node.node_type not in allowed_types):
                checks.append(
                    self._fail(
                        ACCEPTANCE_NODE_ROLE_MISMATCH,
                        f"The scenario-required {role} Node is missing or role-incompatible.",
                    )
                )
        for role, expected_count in scenario.expected_role_counts.items():
            actual_count = sum(node.creative_role == role for node in nodes)
            if actual_count != expected_count:
                checks.append(
                    self._fail(
                        ACCEPTANCE_NODE_ROLE_MISMATCH,
                        f"The scenario requires {expected_count} {role} Nodes; found {actual_count}.",
                    )
                )

    def _check_target(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        nodes_by_role: dict[str, AcceptanceNodeEvidenceV2],
        assets_by_id: dict[str, AcceptanceAssetEvidenceV2],
        evidence: AcceptanceEvidenceV2,
        checks: list[AcceptanceCheckV2],
    ) -> None:
        video = nodes_by_role.get("storyboard_video")
        if video is None or not video.generation_prompt.strip() or not video.structured_content:
            checks.append(
                self._fail(
                    ACCEPTANCE_TARGET_INCOMPLETE,
                    "The requested Video Draft authoring evidence is incomplete.",
                )
            )
            return
        if scenario.target == "video_draft":
            return
        if video.status != "ready":
            checks.append(
                self._fail(
                    ACCEPTANCE_TARGET_INCOMPLETE,
                    "The requested Video Node is not Ready.",
                    video.node_id,
                )
            )
        if not video.provider_terminal:
            checks.append(
                self._fail(
                    ACCEPTANCE_PROVIDER_TERMINAL_EVENT_MISSING,
                    "The Video Node has no correlated terminal provider evidence.",
                    video.node_id,
                )
            )
        self._check_output_asset(video, assets_by_id, checks)
        if scenario.target != "final_export":
            return
        editing = nodes_by_role.get("editing")
        if editing is None or editing.status != "ready":
            checks.append(
                self._fail(
                    ACCEPTANCE_TARGET_INCOMPLETE,
                    "The final Editing Node is missing or not Ready.",
                )
            )
            return
        self._check_output_asset(editing, assets_by_id, checks)
        has_video_binding = any(
            binding.enabled
            and binding.source_node_id == video.node_id
            and binding.target_node_id == editing.node_id
            and binding.input_role == "video_reference"
            for binding in evidence.bindings
        )
        if not has_video_binding:
            checks.append(
                self._fail(
                    ACCEPTANCE_BINDING_MISSING,
                    "The final Editing Node has no enabled Video input Binding.",
                    video.node_id,
                    editing.node_id,
                )
            )

    def _check_output_asset(
        self,
        node: AcceptanceNodeEvidenceV2,
        assets_by_id: dict[str, AcceptanceAssetEvidenceV2],
        checks: list[AcceptanceCheckV2],
    ) -> None:
        asset = assets_by_id.get(node.output_asset_id or "")
        if asset is None or not asset.readable:
            checks.append(
                self._fail(
                    ACCEPTANCE_OUTPUT_ASSET_MISSING,
                    "A canonical readable output Asset is missing.",
                    node.node_id,
                )
            )

    def _check_relationships(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        nodes_by_role: dict[str, AcceptanceNodeEvidenceV2],
        evidence: AcceptanceEvidenceV2,
        checks: list[AcceptanceCheckV2],
    ) -> None:
        for relationship in scenario.required_relationships:
            source = nodes_by_role.get(relationship.source_role)
            target = nodes_by_role.get(relationship.target_role)
            binding = next(
                (
                    item
                    for item in evidence.bindings
                    if item.enabled
                    and source is not None
                    and target is not None
                    and item.source_node_id == source.node_id
                    and item.target_node_id == target.node_id
                    and item.input_role == relationship.input_role
                ),
                None,
            )
            if binding is None:
                checks.append(
                    self._fail(
                        ACCEPTANCE_BINDING_MISSING,
                        "A scenario-required semantic relationship has no enabled Binding.",
                        *(item.node_id for item in (source, target) if item is not None),
                    )
                )
                checks.append(
                    self._fail(
                        ACCEPTANCE_RESOLVED_INPUT_MISSING,
                        "A required relationship is absent from the target run-input snapshot.",
                        *(item.node_id for item in (source, target) if item is not None),
                    )
                )
                if (
                    relationship.require_provider_delivery
                    and relationship.provider_supports_reference
                ):
                    checks.append(
                        self._fail(
                            ACCEPTANCE_PROVIDER_REFERENCE_MISSING,
                            "A required relationship has no provider delivery evidence.",
                            *(item.node_id for item in (source, target) if item is not None),
                        )
                    )
                continue
            if binding.binding_id not in target.run_input_binding_ids:
                checks.append(
                    self._fail(
                        ACCEPTANCE_RESOLVED_INPUT_MISSING,
                        "A required Binding is absent from the target run-input snapshot.",
                        binding.binding_id,
                    )
                )
            if (
                relationship.require_provider_delivery
                and relationship.provider_supports_reference
                and source.output_asset_id
                and source.output_asset_id not in target.submitted_reference_asset_ids
            ):
                checks.append(
                    self._fail(
                        ACCEPTANCE_PROVIDER_REFERENCE_MISSING,
                        "A supported required source Asset is absent from provider delivery evidence.",
                        source.output_asset_id,
                        target.node_id,
                    )
                )

    def _check_prompts(
        self,
        nodes_by_role: dict[str, AcceptanceNodeEvidenceV2],
        checks: list[AcceptanceCheckV2],
    ) -> None:
        product = nodes_by_role.get("product")
        if product is not None:
            normalized = product.generation_prompt.casefold()
            moving_directives = ("camera move", "animate", "five-second", "timed video")
            if any(term in normalized for term in moving_directives):
                checks.append(
                    self._fail(
                        ACCEPTANCE_PROMPT_ROLE_MISMATCH,
                        "The Product image prompt contains a timed-video directive.",
                        product.node_id,
                    )
                )
        storyboard = nodes_by_role.get("storyboard_sequence")
        if storyboard is not None:
            panels = storyboard.structured_content.get("panels")
            panel_count = (
                len(panels)
                if isinstance(panels, (list, tuple))
                else storyboard.structured_content.get("panel_count")
            )
            grid = str(storyboard.structured_content.get("grid") or "").casefold()
            prompt = storyboard.generation_prompt.casefold()
            if panel_count != 9 or "3x3" not in f"{grid} {prompt}":
                checks.append(
                    self._fail(
                        ACCEPTANCE_PROMPT_ROLE_MISMATCH,
                        "The Storyboard prompt does not define one ordered 3x3 grid.",
                        storyboard.node_id,
                    )
                )

    def _check_guidance(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        evidence: AcceptanceEvidenceV2,
        checks: list[AcceptanceCheckV2],
    ) -> None:
        if scenario.require_guidance_complete and evidence.guidance_status != "completed":
            checks.append(
                self._fail(
                    ACCEPTANCE_GUIDANCE_INCOMPLETE,
                    "The scenario requires a completed Guidance session.",
                )
            )
        if scenario.require_guidance_complete and (
            evidence.active_proposal_id or evidence.open_continuation_ids
        ):
            checks.append(
                self._fail(
                    ACCEPTANCE_UNEXPECTED_CONTINUATION,
                    "The completed journey still has an open Proposal or continuation.",
                )
            )

    def _check_media_parameters(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        nodes_by_role: dict[str, AcceptanceNodeEvidenceV2],
        checks: list[AcceptanceCheckV2],
    ) -> None:
        if scenario.target == "video_draft":
            return
        video = nodes_by_role.get("storyboard_video")
        if video is None:
            return
        mismatches: list[str] = []
        requested = scenario.requested_parameters
        effective = video.effective_parameters
        actual = video.actual_media_facts
        expected_ratio = requested.get("aspect_ratio")
        if expected_ratio and effective.get("aspect_ratio") != expected_ratio:
            mismatches.append("effective aspect ratio")
        if expected_ratio == "16:9":
            width = actual.get("width")
            height = actual.get("height")
            if not _ratio_matches(width, height, 16 / 9):
                mismatches.append("actual aspect ratio")
        expected_duration = effective.get("duration_seconds", requested.get("duration_seconds"))
        actual_duration = actual.get("duration_seconds")
        if _is_number(expected_duration) and (
            not _is_number(actual_duration)
            or abs(float(actual_duration) - float(expected_duration)) > 1.0
        ):
            mismatches.append("actual duration")
        if scenario.audio_policy == "no_bgm" and actual.get("has_audio") is not True:
            mismatches.append("native video audio")
        if mismatches:
            checks.append(
                self._fail(
                    ACCEPTANCE_MEDIA_PARAMETER_MISMATCH,
                    f"Media evidence does not match: {', '.join(mismatches)}.",
                    video.node_id,
                )
            )


def assert_creative_review_complete(report: ProgressiveAcceptanceReportV2) -> None:
    """Reject a creative-acceptance claim while the human review is pending."""

    if report.creative_review.status == "pending":
        raise ValueError(ACCEPTANCE_CREATIVE_REVIEW_PENDING)


def classify_acceptance_report(payload: dict[str, Any]) -> Literal["current", "legacy"]:
    """Classify old report files without mutating or reverse-migrating them."""

    return "current" if payload.get("schema_version") == "2" else "legacy"


class ProgressiveAcceptanceReportStore:
    """Persist immutable acceptance attempts and validated resume lineage."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def append(
        self,
        scenario: ProgressiveAcceptanceScenarioV2,
        report: ProgressiveAcceptanceReportV2,
    ) -> Path:
        run_dir = self._run_dir(report.acceptance_run_id)
        if run_dir.exists():
            raise FileExistsError(report.acceptance_run_id)
        lineage = self._lineage(report.parent_run_id)
        resume_count = len(lineage)
        cumulative = report.attempt_elapsed_seconds + sum(
            item.attempt_elapsed_seconds for item in lineage
        )
        persisted = report.model_copy(
            update={
                "resume_count": resume_count,
                "cumulative_elapsed_seconds": round(cumulative, 3),
            }
        )
        run_dir.mkdir(parents=True, exist_ok=False)
        _write_json(run_dir / "scenario.json", scenario.model_dump(mode="json"))
        _write_json(
            run_dir / "creative-review.json", persisted.creative_review.model_dump(mode="json")
        )
        report_path = run_dir / "report.json"
        _write_json(report_path, _sanitize(persisted.model_dump(mode="json")))
        return report_path

    def load(self, run_id: str) -> ProgressiveAcceptanceReportV2:
        path = self._run_dir(run_id) / "report.json"
        return ProgressiveAcceptanceReportV2.model_validate_json(path.read_text(encoding="utf-8"))

    def _lineage(self, parent_run_id: str | None) -> list[ProgressiveAcceptanceReportV2]:
        lineage: list[ProgressiveAcceptanceReportV2] = []
        seen: set[str] = set()
        current = parent_run_id
        while current is not None:
            if current in seen:
                raise ValueError(ACCEPTANCE_ATTEMPT_LINEAGE_INVALID)
            seen.add(current)
            path = self._run_dir(current) / "report.json"
            if not path.is_file():
                raise ValueError(ACCEPTANCE_ATTEMPT_LINEAGE_INVALID)
            parent = ProgressiveAcceptanceReportV2.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            lineage.append(parent)
            current = parent.parent_run_id
            if len(lineage) > 100:
                raise ValueError(ACCEPTANCE_ATTEMPT_LINEAGE_INVALID)
        return lineage

    def _run_dir(self, run_id: str) -> Path:
        return self._root / "runs" / run_id


def _ratio_matches(width: object, height: object, expected: float) -> bool:
    if not _is_number(width) or not _is_number(height) or float(height) <= 0:
        return False
    return abs(float(width) / float(height) - expected) <= 0.02


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _guidance_status(guidance: dict[str, Any]) -> str | None:
    explicit = guidance.get("status") or guidance.get("session_status")
    if explicit == "completed":
        return "completed"
    topics = tuple(item for item in guidance.get("topics") or [] if isinstance(item, dict))
    terminal = {"selected", "deferred", "excluded", "completed"}
    if (
        topics
        and not guidance.get("active_proposal_id")
        and all(item.get("status") in terminal for item in topics)
    ):
        return "completed"
    return str(explicit) if explicit else ("active" if guidance else None)


def _event_payloads(
    events: tuple[dict[str, Any], ...],
    *,
    prefix: str,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "event_type": str(item.get("event_type") or ""),
            "node_id": item.get("node_id"),
            **{
                str(key): value
                for key, value in (item.get("payload") or {}).items()
                if str(key).casefold() not in _SENSITIVE_KEYS
            },
        }
        for item in events
        if str(item.get("event_type") or "").startswith(prefix)
    )


def _last_scalar(payloads: tuple[dict[str, Any], ...], *keys: str) -> str | None:
    for payload in reversed(payloads):
        for key in keys:
            value = payload.get(key)
            if value is not None and not isinstance(value, (dict, list, tuple)):
                return str(value)
    return None


def _last_mapping(payloads: tuple[dict[str, Any], ...], key: str) -> dict[str, Any]:
    for payload in reversed(payloads):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _merged_ids(payloads: tuple[dict[str, Any], ...], *keys: str) -> tuple[str, ...]:
    values: list[str] = []
    for payload in payloads:
        for key in keys:
            candidate = payload.get(key)
            if isinstance(candidate, (list, tuple)):
                for item in candidate:
                    identity = str(item)
                    if identity and identity not in values:
                        values.append(identity)
    return tuple(values)


def _media_input_ids(
    payloads: tuple[dict[str, Any], ...],
    key: str,
    *,
    require_transport: bool = False,
) -> tuple[str, ...]:
    values: list[str] = []
    for payload in payloads:
        for item in payload.get("media_inputs") or []:
            if not isinstance(item, dict):
                continue
            if require_transport and not item.get("transport_type"):
                continue
            identity = str(item.get(key) or "")
            if identity and identity not in values:
                values.append(identity)
    return tuple(values)


def _merge_id_groups(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(identity for group in groups for identity in group))


_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "secret",
    "signed_payload",
    "token",
}


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.casefold() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(item, key=str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and value.startswith("/"):
        return "[redacted-path]"
    return value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
