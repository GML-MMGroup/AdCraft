"""Run bounded progressive Agent Canvas acceptance through public HTTP APIs only."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Literal
from uuid import uuid4

import httpx

from scripts.agent_canvas_progressive_acceptance import (
    AcceptanceRelationshipV2,
    CreativeReviewV2,
    ProgressiveAcceptanceEvidenceCollector,
    ProgressiveAcceptanceEvaluator,
    ProgressiveAcceptanceReportStore,
    ProgressiveAcceptanceScenarioV2,
    ProgressiveMediaProbeCache,
)


TERMINAL_TURNS = {"completed", "failed"}
TERMINAL_EXECUTIONS = {"completed", "partial_failed", "failed", "cancelled"}
DecisionMode = Literal["user", "agent-recommended"]
JourneyTarget = Literal["video-draft", "final-video"]
AcceptanceTarget = Literal["video_draft", "ready_video", "final_export"]
ScenarioName = Literal["standard", "all-elements-30s"]


class AcceptanceFailure(RuntimeError):
    """A safe, classified acceptance failure."""

    def __init__(self, code: str, message: str, *, blocked: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.blocked = blocked


def stable_idempotency_key(run_id: str, stage: str, identity: str, step: int) -> str:
    digest = hashlib.sha256(f"{run_id}:{stage}:{identity}:{step}".encode()).hexdigest()[:20]
    return f"progressive-{stage}-{digest}"


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _descriptor(proposal: dict[str, Any], action: str) -> dict[str, Any]:
    found = next(
        (
            item
            for item in proposal.get("actions", [])
            if item.get("action") == action and item.get("enabled", True)
        ),
        None,
    )
    if found is None:
        raise AcceptanceFailure(
            "acceptance_proposal_action_missing",
            f"The current Proposal does not allow {action}.",
        )
    return found


def _applied_option(proposal: dict[str, Any]) -> dict[str, str] | None:
    application = proposal.get("latest_application") or {}
    option_id = application.get("option_id")
    option = next(
        (item for item in proposal.get("options") or [] if item.get("option_id") == option_id),
        None,
    )
    if option is None:
        return None
    return {"option_id": str(option_id), "title": str(option.get("title") or "")}


class UserOptionPolicy:
    def action(self, proposal: dict[str, Any], *, step: int) -> dict[str, Any]:
        descriptor = _descriptor(proposal, "select_option")
        options = list(proposal.get("options") or [])
        if not options:
            raise AcceptanceFailure("acceptance_proposal_empty", "Proposal has no public options.")
        selected = options[step % len(options)]
        accepted_references = list(proposal.get("proposed_references", []))
        return {
            "action_id": descriptor["action_id"],
            "action": "select_option",
            "expected_session_revision": descriptor["expected_session_revision"],
            "option_id": selected["option_id"],
            "accepted_references": accepted_references,
        }


class DelegatedOptionPolicy:
    def action(self, proposal: dict[str, Any], *, step: int) -> dict[str, Any]:
        del step
        descriptor = _descriptor(proposal, "delegate_choice")
        return {
            "action_id": descriptor["action_id"],
            "action": "delegate_choice",
            "expected_session_revision": descriptor["expected_session_revision"],
        }


def current_proposal_id(timeline: dict[str, Any]) -> str | None:
    guidance = timeline.get("guidance_session")
    if isinstance(guidance, dict) and guidance.get("active_proposal_id"):
        return str(guidance["active_proposal_id"])
    for item in reversed(list(timeline.get("items") or [])):
        proposal = item.get("proposal")
        if isinstance(proposal, dict) and proposal.get("availability") in {"current", "open"}:
            return str(proposal["proposal_id"])
    return None


def guidance_resume_instruction(timeline: dict[str, Any]) -> tuple[str, str] | None:
    guidance = timeline.get("guidance_session")
    if not isinstance(guidance, dict) or guidance.get("active_proposal_id"):
        return None
    continuations = list(timeline.get("continuations") or [])
    if any(
        item.get("status") in {"queued", "leased", "running", "waiting"} for item in continuations
    ):
        return None
    items = list(timeline.get("items") or [])
    if not items:
        return None
    latest = items[-1]
    resume_identity = None
    if latest.get("entry_type") == "message" and str(latest.get("speaker") or "").startswith(
        "adcraft_"
    ):
        resume_identity = latest.get("entry_id")
    elif continuations:
        continuation = continuations[-1]
        if (
            continuation.get("operation") == "next_action"
            and continuation.get("status") == "failed"
        ):
            resume_identity = continuation.get("continuation_id")
    if not resume_identity:
        return None

    settled = {
        str(item.get("topic_kind"))
        for item in guidance.get("topics") or []
        if item.get("status") in {"selected", "deferred", "excluded"}
    }
    included = [
        str(item.get("element_kind"))
        for item in guidance.get("element_decisions") or []
        if item.get("presence") == "include"
    ]
    remaining = [item for item in included if item not in settled]
    if not remaining:
        return None
    selected = [
        str(item.get("topic_kind"))
        for item in guidance.get("topics") or []
        if item.get("status") == "selected"
    ]
    excluded = [
        str(item.get("element_kind"))
        for item in guidance.get("element_decisions") or []
        if item.get("presence") == "exclude"
    ]

    def display(values: list[str]) -> str:
        return ", ".join(value.replace("_", " ").title() for value in values)

    clauses = [f"Continue with the remaining included creative elements: {display(remaining)}."]
    if selected:
        clauses.append(
            f"{display(selected)} are already selected; use their existing Drafts as context "
            "instead of recreating them."
        )
    if excluded:
        clauses.append(f"Keep {display(excluded)} excluded.")
    clauses.append("Preserve the original request constraints and do not generate media.")
    return str(resume_identity), " ".join(clauses)


@dataclass
class JourneyBounds:
    timeout_seconds: float
    max_actions: int = 24
    max_repeats: int = 2
    now: Callable[[], float] = time.monotonic
    started_at: float | None = None
    action_count: int = 0
    _proposal_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.started_at is None:
            self.started_at = self.now()

    def require_time(self, description: str) -> None:
        if self.now() >= float(self.started_at) + self.timeout_seconds:
            raise AcceptanceFailure("acceptance_timeout", f"Timed out waiting for {description}.")

    def observe_proposal(self, digest: str) -> None:
        self.action_count += 1
        if self.action_count > self.max_actions:
            raise AcceptanceFailure(
                "acceptance_proposal_loop", "Proposal action bound was exceeded."
            )
        count = self._proposal_counts.get(digest, 0) + 1
        self._proposal_counts[digest] = count
        if count > self.max_repeats:
            raise AcceptanceFailure(
                "acceptance_proposal_loop", "The same Proposal repeated without progress."
            )


@dataclass
class ProgressiveAcceptanceReport:
    run_id: str
    scenario_id: str
    decision_mode: DecisionMode
    through: JourneyTarget
    status: str = "running"
    project_id: str | None = None
    workflow_id: str | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    provider_tasks: list[dict[str, Any]] = field(default_factory=list)
    event_cursor: int | None = None
    probe: dict[str, Any] | None = None
    optional_bgm: dict[str, Any] = field(default_factory=dict)
    error: dict[str, str] | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_seconds: float | None = None
    _request_text: str = ""
    _prompt_snapshots: list[dict[str, Any]] = field(default_factory=list)
    _workflow_snapshot: dict[str, Any] = field(default_factory=dict)
    _timeline_snapshot: dict[str, Any] = field(default_factory=dict)
    _runtime_snapshot: dict[str, Any] = field(default_factory=dict)
    _event_snapshot: dict[str, Any] = field(default_factory=dict)
    _asset_snapshot: dict[str, Any] = field(default_factory=dict)
    _final_media_bytes: bytes | None = None

    def record_decision(
        self,
        *,
        proposal_kind: str,
        proposal_id: str,
        action: str,
        option_id: str | None,
        title: str | None,
        source_action: str | None = None,
        accepted_reference_ids: list[str] | None = None,
    ) -> None:
        self.decisions.append(
            {
                "proposal_kind": proposal_kind,
                "proposal_id": proposal_id,
                "action": action,
                "option_id": option_id,
                "title": title,
                "source_action": source_action,
                "accepted_reference_ids": accepted_reference_ids or [],
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": "agent-canvas-progressive-acceptance-v1",
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "decision_mode": self.decision_mode,
            "through": self.through,
            "status": self.status,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "decisions": self.decisions,
            "nodes": self.nodes,
            "bindings": self.bindings,
            "assets": self.assets,
            "provider_tasks": self.provider_tasks,
            "event_cursor": self.event_cursor,
            "probe": self.probe,
            "optional_bgm": self.optional_bgm,
            "error": self.error,
            "started_at": self.started_at,
            "duration_seconds": self.duration_seconds,
        }

    def review_dict(self) -> dict[str, Any]:
        return {
            "contract": "agent-canvas-progressive-prompt-review-v1",
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "synthetic_request": self._request_text,
            "selected_public_concepts": self.decisions,
            "node_prompt_snapshots": self._prompt_snapshots,
            "review_rubric": {
                "request_relevance": None,
                "constraint_preservation": None,
                "capability_isolation": None,
                "visual_and_action_specificity": None,
                "storyboard_continuity": None,
                "reference_use": None,
                "video_readiness": None,
                "nonblank_semantic_match": None,
            },
        }


class ProgressiveJourneyClient:
    """The sole HTTP boundary used by the acceptance driver."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=30)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(self, path: str) -> tuple[dict[str, Any], httpx.Headers]:
        response = self._client.get(path)
        return self._json_response(response)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        idempotency_key: str,
        etag: str | None = None,
    ) -> tuple[dict[str, Any], httpx.Headers]:
        headers = {"Idempotency-Key": idempotency_key}
        if etag is not None:
            headers["If-Match"] = etag
        response = self._client.post(path, json=body, headers=headers)
        return self._json_response(response)

    def patch(
        self, path: str, body: dict[str, Any], *, etag: str
    ) -> tuple[dict[str, Any], httpx.Headers]:
        response = self._client.patch(path, json=body, headers={"If-Match": etag})
        return self._json_response(response)

    def bytes(self, url: str) -> tuple[bytes, httpx.Headers]:
        response = self._client.get(url)
        if response.status_code != 200:
            self._raise(response)
        return response.content, response.headers

    @classmethod
    def _json_response(cls, response: httpx.Response) -> tuple[dict[str, Any], httpx.Headers]:
        if not response.is_success:
            cls._raise(response)
        return response.json(), response.headers

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        code = f"http_{response.status_code}"
        message = "Progressive acceptance HTTP request failed."
        try:
            detail = response.json().get("detail", {})
            if isinstance(detail, dict):
                code = str(detail.get("code") or code)
                message = str(detail.get("message") or message)
        except (ValueError, AttributeError):
            pass
        raise AcceptanceFailure(code, message)


class ProgressiveJourneyDriver:
    def __init__(
        self,
        client: ProgressiveJourneyClient,
        *,
        decision_mode: DecisionMode,
        through: JourneyTarget,
        timeout_seconds: int,
        poll_interval: float = 1.0,
        resume_workflow_id: str | None = None,
        acceptance_target: AcceptanceTarget | None = None,
        require_guidance_complete: bool = False,
        scenario_name: ScenarioName = "standard",
    ) -> None:
        self.client = client
        self.decision_mode = decision_mode
        self.through = through
        self.bounds = JourneyBounds(timeout_seconds=timeout_seconds)
        self.poll_interval = poll_interval
        self.policy = UserOptionPolicy() if decision_mode == "user" else DelegatedOptionPolicy()
        self.resume_workflow_id = resume_workflow_id
        self.acceptance_target = acceptance_target or (
            "video_draft" if through == "video-draft" else "final_export"
        )
        self.require_guidance_complete = require_guidance_complete
        self.scenario_name = scenario_name
        self._handled_resume_messages: set[str] = set()

    def run(self, report: ProgressiveAcceptanceReport) -> None:
        self._preflight()
        if self.resume_workflow_id is not None:
            workflow, _ = self.client.get(f"/api/v2/workflows/{self.resume_workflow_id}")
            report.project_id = workflow.get("project_id")
            report.workflow_id = self.resume_workflow_id
            report._request_text = _scenario_prompt(
                self.through,
                self.decision_mode,
                scenario_name=self.scenario_name,
            )
            self._advance_guidance(report)
            workflow, _ = self.client.get(f"/api/v2/workflows/{self.resume_workflow_id}")
            timeline, _ = self.client.get(
                f"/api/v2/workflows/{self.resume_workflow_id}/chat/timeline?limit=200"
            )
            report._timeline_snapshot = timeline
            self._restore_applied_decisions(report, timeline)
            _assert_draft_contract(workflow)
            if self.scenario_name == "all-elements-30s":
                workflow = self._prepare_all_elements_graph(report, workflow)
            _assert_scenario_constraints(
                workflow,
                timeline,
                through=self.through,
                scenario_name=self.scenario_name,
            )
            self._record_workflow(report, workflow)
            if self.acceptance_target == "video_draft":
                self._assert_manual_media(report, self.resume_workflow_id)
            elif self.acceptance_target == "ready_video":
                self._complete_ready_video(report, workflow)
            else:
                self._complete_final_video(report, workflow)
            return
        project, _ = self.client.post(
            "/api/v2/projects",
            {"name": f"Progressive acceptance {report.run_id[-8:]}"},
            idempotency_key=stable_idempotency_key(report.run_id, "project", "create", 0),
        )
        report.project_id = str(project["project_id"])
        report.workflow_id = str(project["workflow_id"])
        workflow_id = report.workflow_id
        settings, headers = self.client.get(f"/api/v2/workflows/{workflow_id}/agent-settings")
        etag = headers.get("etag")
        if not etag:
            raise AcceptanceFailure("acceptance_etag_missing", "Agent Settings ETag is missing.")
        mode = (
            "manual"
            if self.scenario_name == "all-elements-30s"
            else "automatic"
            if self.through == "final-video"
            else "manual"
        )
        self.client.patch(
            f"/api/v2/workflows/{workflow_id}/agent-settings",
            {"media_execution_mode": mode},
            etag=etag,
        )
        prompt = _scenario_prompt(
            self.through,
            self.decision_mode,
            scenario_name=self.scenario_name,
        )
        report._request_text = prompt
        accepted, _ = self.client.post(
            f"/api/v2/workflows/{workflow_id}/chat/messages",
            {"text": prompt},
            idempotency_key=stable_idempotency_key(report.run_id, "chat", "initial", 0),
        )
        self._wait_turn(workflow_id, str(accepted["turn_id"]))
        self._advance_guidance(report)
        workflow, _ = self.client.get(f"/api/v2/workflows/{workflow_id}")
        timeline, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/chat/timeline?limit=200")
        report._timeline_snapshot = timeline
        self._restore_applied_decisions(report, timeline)
        _assert_draft_contract(workflow)
        if self.scenario_name == "all-elements-30s":
            workflow = self._prepare_all_elements_graph(report, workflow)
        _assert_scenario_constraints(
            workflow,
            timeline,
            through=self.through,
            scenario_name=self.scenario_name,
        )
        self._record_workflow(report, workflow)
        if self.acceptance_target == "video_draft":
            self._assert_manual_media(report, workflow_id)
        elif self.acceptance_target == "ready_video":
            self._complete_ready_video(report, workflow)
        else:
            self._complete_final_video(report, workflow)

    def _preflight(self) -> None:
        health, _ = self.client.get("/api/v2/health")
        if health.get("status") != "ok":
            raise AcceptanceFailure(
                "acceptance_preflight_blocked", "FastAPI/Pi health is unavailable.", blocked=True
            )
        # Agent cognition is covered by the supervised FastAPI/Pi health check.
        # The compatibility capability endpoint exposes media models only.
        output_types = (
            ()
            if self.through == "video-draft"
            else ("image", "video", "audio")
            if self.scenario_name == "all-elements-30s"
            else ("image", "video")
        )
        for output_type in output_types:
            capabilities, _ = self.client.get(
                f"/api/v2/provider-models/capabilities?output_type={output_type}"
            )
            if not list(capabilities.get("items") or []):
                raise AcceptanceFailure(
                    "acceptance_preflight_blocked",
                    f"No available {output_type} capability is configured.",
                    blocked=True,
                )
        if self.through == "final-video" and (
            shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None
        ):
            raise AcceptanceFailure(
                "acceptance_preflight_blocked", "FFmpeg and ffprobe are required.", blocked=True
            )

    def _wait_turn(self, workflow_id: str, turn_id: str) -> dict[str, Any]:
        while True:
            self.bounds.require_time("Agent turn")
            turn, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/chat/turns/{turn_id}")
            if turn.get("status") in TERMINAL_TURNS:
                if turn.get("status") != "completed":
                    raise AcceptanceFailure(
                        str(turn.get("error_code") or "acceptance_turn_failed"),
                        str(turn.get("error_message") or "Agent turn failed."),
                    )
                return turn
            time.sleep(self.poll_interval)

    def _advance_guidance(self, report: ProgressiveAcceptanceReport) -> None:
        assert report.workflow_id is not None
        workflow_id = report.workflow_id
        while True:
            self.bounds.require_time("progressive guidance")
            workflow, _ = self.client.get(f"/api/v2/workflows/{workflow_id}")
            timeline, _ = self.client.get(
                f"/api/v2/workflows/{workflow_id}/chat/timeline?limit=200"
            )
            report._workflow_snapshot = workflow
            report._timeline_snapshot = timeline
            if _video_draft_ready(workflow) and (
                not self.require_guidance_complete or _guidance_complete(timeline)
            ):
                return
            proposal_id = current_proposal_id(timeline)
            if proposal_id is None:
                resume = guidance_resume_instruction(timeline)
                if resume is not None and resume[0] not in self._handled_resume_messages:
                    entry_id, instruction = resume
                    self._handled_resume_messages.add(entry_id)
                    self.bounds.action_count += 1
                    if self.bounds.action_count > self.bounds.max_actions:
                        raise AcceptanceFailure(
                            "acceptance_proposal_loop", "Guidance action bound was exceeded."
                        )
                    accepted, _ = self.client.post(
                        f"/api/v2/workflows/{workflow_id}/chat/messages",
                        {"text": instruction},
                        idempotency_key=stable_idempotency_key(
                            report.run_id,
                            "chat-resume",
                            entry_id,
                            self.bounds.action_count,
                        ),
                    )
                    self._wait_turn(workflow_id, str(accepted["turn_id"]))
                    continue
                time.sleep(self.poll_interval)
                continue
            proposal, _ = self.client.get(
                f"/api/v2/workflows/{workflow_id}/chat/proposals/{proposal_id}"
            )
            proposal_digest = _digest(
                {
                    "proposal_kind": proposal.get("proposal_kind"),
                    "options": [item.get("option_id") for item in proposal.get("options", [])],
                    "source_action": proposal.get("source_action"),
                }
            )
            self.bounds.observe_proposal(proposal_digest)
            action = self.policy.action(proposal, step=self.bounds.action_count - 1)
            option = next(
                (
                    item
                    for item in proposal.get("options", [])
                    if item.get("option_id") == action.get("option_id")
                ),
                None,
            )
            report.record_decision(
                proposal_kind=str(proposal.get("proposal_kind")),
                proposal_id=proposal_id,
                action=str(action["action"]),
                option_id=action.get("option_id"),
                title=str(option.get("title")) if option else None,
                source_action=proposal.get("source_action"),
                accepted_reference_ids=[
                    str(item.get("source_id")) for item in action.get("accepted_references", [])
                ],
            )
            accepted, _ = self.client.post(
                f"/api/v2/workflows/{workflow_id}/chat/proposals/{proposal_id}/actions",
                action,
                idempotency_key=stable_idempotency_key(
                    report.run_id, "proposal", proposal_id, self.bounds.action_count
                ),
            )
            self._wait_turn(workflow_id, str(accepted["turn_id"]))
            if action["action"] == "delegate_choice":
                applied_proposal, _ = self.client.get(
                    f"/api/v2/workflows/{workflow_id}/chat/proposals/{proposal_id}"
                )
                applied = _applied_option(applied_proposal)
                if applied is not None:
                    report.decisions[-1]["option_id"] = applied["option_id"]
                    report.decisions[-1]["title"] = applied["title"]

    def _restore_applied_decisions(
        self,
        report: ProgressiveAcceptanceReport,
        timeline: dict[str, Any],
    ) -> None:
        if report.decisions or report.workflow_id is None:
            return
        seen: set[str] = set()
        for item in timeline.get("items") or []:
            if item.get("entry_type") != "concept_proposal":
                continue
            embedded = item.get("proposal") or {}
            metadata = item.get("metadata") or {}
            proposal_id = str(embedded.get("proposal_id") or metadata.get("proposal_id") or "")
            if not proposal_id or proposal_id in seen:
                continue
            seen.add(proposal_id)
            proposal, _ = self.client.get(
                f"/api/v2/workflows/{report.workflow_id}/chat/proposals/{proposal_id}"
            )
            applied = _applied_option(proposal)
            if applied is None:
                continue
            application = proposal.get("latest_application") or {}
            report.record_decision(
                proposal_kind=str(proposal.get("proposal_kind") or ""),
                proposal_id=proposal_id,
                action=str(application.get("action") or "select_option"),
                option_id=applied["option_id"],
                title=applied["title"],
                source_action=proposal.get("source_action"),
                accepted_reference_ids=[
                    str(reference.get("source_id"))
                    for reference in proposal.get("proposed_references") or []
                    if reference.get("source_id")
                ],
            )

    def _record_workflow(
        self, report: ProgressiveAcceptanceReport, workflow: dict[str, Any]
    ) -> None:
        report._workflow_snapshot = workflow
        report.nodes = [
            {
                "node_id": node.get("node_id"),
                "node_type": node.get("node_type"),
                "creative_role": node.get("creative_role"),
                "status": node.get("status"),
                "prompt_length": len(str(node.get("generation_prompt") or "")),
                "prompt_digest": _digest(str(node.get("generation_prompt") or "")),
                "output_asset_id": node.get("output_asset_id"),
            }
            for node in workflow.get("nodes", [])
        ]
        report._prompt_snapshots = [
            {
                "node_id": node.get("node_id"),
                "node_type": node.get("node_type"),
                "creative_role": node.get("creative_role"),
                "summary_prompt": node.get("summary_prompt"),
                "generation_prompt": node.get("generation_prompt"),
            }
            for node in workflow.get("nodes", [])
            if node.get("summary_prompt") or node.get("generation_prompt")
        ]
        bgm_nodes = [
            node
            for node in workflow.get("nodes", [])
            if node.get("node_type") == "audio" or node.get("creative_role") == "bgm"
        ]
        report.optional_bgm = {
            "requested": bool(bgm_nodes),
            "statuses": [node.get("status") for node in bgm_nodes],
            "blocking": False,
        }
        report.bindings = [
            {
                "binding_id": item.get("binding_id"),
                "target_node_id": item.get("target_node_id"),
                "source_node_id": (item.get("source") or {}).get("source_node_id"),
                "source_asset_id": (item.get("source") or {}).get("source_asset_id"),
                "input_role": item.get("input_role"),
                "enabled": item.get("enabled"),
            }
            for item in workflow.get("bindings", [])
        ]
        enabled_sources = {
            str(item.get("source_node_id") or item.get("source_asset_id"))
            for item in report.bindings
            if item.get("enabled") is not False
        }
        required_sources = {
            str(source_id)
            for decision in report.decisions
            for source_id in decision.get("accepted_reference_ids", [])
        }
        missing_sources = sorted(required_sources - enabled_sources)
        if missing_sources:
            raise AcceptanceFailure(
                "acceptance_binding_mismatch",
                "One or more accepted references are missing an enabled Binding.",
            )

    def _prepare_all_elements_graph(
        self,
        report: ProgressiveAcceptanceReport,
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        if report.workflow_id is None:
            raise AcceptanceFailure(
                "acceptance_workflow_missing",
                "The all-elements scenario has no Workflow identity.",
            )
        workflow_id = report.workflow_id
        workflow, headers = self.client.get(f"/api/v2/workflows/{workflow_id}")
        etag = headers.get("etag")
        if not etag:
            raise AcceptanceFailure(
                "acceptance_etag_missing",
                "Workflow ETag is missing for all-elements preparation.",
            )

        def nodes_for(role: str) -> list[dict[str, Any]]:
            return [
                node for node in workflow.get("nodes") or [] if node.get("creative_role") == role
            ]

        def patch_node(node: dict[str, Any], body: dict[str, Any]) -> None:
            nonlocal workflow, etag
            updated, mutation_headers = self.client.patch(
                f"/api/v2/workflows/{workflow_id}/nodes/{node['node_id']}",
                body,
                etag=etag,
            )
            workflow = updated.get("workflow") or workflow
            etag = mutation_headers.get("etag") or etag

        storyboards = nodes_for("storyboard_sequence")
        videos = nodes_for("storyboard_video")
        bgm_nodes = nodes_for("bgm")
        if len(storyboards) != 1 or len(videos) != 1 or len(bgm_nodes) != 1:
            raise AcceptanceFailure(
                "acceptance_constraint_mismatch",
                "Guidance must produce one initial Storyboard, Video, and BGM before expansion.",
            )
        storyboard_a = storyboards[0]
        video_a = videos[0]
        bgm = bgm_nodes[0]
        patch_node(
            storyboard_a,
            {
                "title": "Storyboard A (0-15 seconds)",
                "generation_prompt": (
                    f"{storyboard_a.get('generation_prompt') or ''}\n\n"
                    "Sequence A covers 0-15 seconds and establishes the product, curator, and setting."
                ).strip(),
            },
        )
        storyboard_a = nodes_for("storyboard_sequence")[0]
        created_storyboard, mutation_headers = self.client.post(
            f"/api/v2/workflows/{workflow_id}/nodes",
            {
                "node_type": "image",
                "creative_role": "storyboard_sequence",
                "title": "Storyboard B (15-30 seconds)",
                "summary_prompt": (
                    "Complete the campaign with the curator serving the sparkling tea, then "
                    "settle on the final bottle-and-glass brand tableau."
                ),
                "generation_prompt": (
                    "Begin from Sequence A's poised first-pour state. Show the curator completing "
                    "the pour, effervescence rising through the glass, the tasting-cup ritual, "
                    "and a decisive bottle-and-glass final brand beat. This 15-30 second sequence "
                    "must advance beyond the establishing actions in Sequence A."
                ),
                "structured_content": _all_elements_storyboard_b_content(storyboard_a),
                "parameters": storyboard_a.get("parameters") or {},
                "position": {
                    "x": float((storyboard_a.get("position") or {}).get("x") or 0) + 360,
                    "y": float((storyboard_a.get("position") or {}).get("y") or 0),
                },
                "clone_inputs_from_node_id": storyboard_a["node_id"],
            },
            idempotency_key=stable_idempotency_key(report.run_id, "storyboard", "sequence-b", 0),
            etag=etag,
        )
        workflow = created_storyboard.get("workflow") or workflow
        etag = mutation_headers.get("etag") or etag
        storyboard_b = created_storyboard.get("node")
        if not isinstance(storyboard_b, dict):
            raise AcceptanceFailure(
                "acceptance_target_incomplete",
                "Storyboard B creation returned no Node.",
            )
        patch_node(
            video_a,
            {
                "title": "Video A (0-15 seconds)",
                "structured_content": {
                    **(video_a.get("structured_content") or {}),
                    "duration_seconds": 15,
                },
                "parameters": {
                    **(video_a.get("parameters") or {}),
                    "duration_seconds": 15,
                    "aspect_ratio": "16:9",
                },
            },
        )
        video_a = nodes_for("storyboard_video")[0]
        created_video, mutation_headers = self.client.post(
            f"/api/v2/workflows/{workflow_id}/nodes",
            {
                "node_type": "video",
                "creative_role": "storyboard_video",
                "title": "Video B (15-30 seconds)",
                "summary_prompt": (
                    "The curator completes the pour and resolves the ritual in a final brand beat."
                ),
                "generation_prompt": (
                    "Continue from Sequence A's closing pose and bottle position. Track the "
                    "completed sparkling pour, the curator's tasting-cup presentation, and a "
                    "calm push-in to the bottle-and-glass final brand beat. Preserve live-action "
                    "cinematic treatment and do not repeat Sequence A's establishing move."
                ),
                "structured_content": _all_elements_video_b_content(),
                "parameters": {
                    **(video_a.get("parameters") or {}),
                    "duration_seconds": 15,
                    "aspect_ratio": "16:9",
                },
                "position": {
                    "x": float((video_a.get("position") or {}).get("x") or 0) + 360,
                    "y": float((video_a.get("position") or {}).get("y") or 0),
                },
            },
            idempotency_key=stable_idempotency_key(report.run_id, "video", "segment-b", 0),
            etag=etag,
        )
        workflow = created_video.get("workflow") or workflow
        etag = mutation_headers.get("etag") or etag
        video_b = created_video.get("node")
        if not isinstance(video_b, dict):
            raise AcceptanceFailure(
                "acceptance_target_incomplete",
                "Video B creation returned no Node.",
            )
        role_by_node_id = {
            str(node.get("node_id")): str(node.get("creative_role"))
            for node in workflow.get("nodes") or []
        }
        source_bindings = [
            binding
            for binding in workflow.get("bindings") or []
            if binding.get("target_node_id") == video_a["node_id"]
            and binding.get("enabled") is not False
        ]
        for index, binding in enumerate(source_bindings):
            source = dict(binding.get("source") or {})
            if (
                source.get("kind") == "node_output"
                and role_by_node_id.get(str(source.get("source_node_id"))) == "storyboard_sequence"
            ):
                source["source_node_id"] = storyboard_b["node_id"]
            _, mutation_headers = self.client.post(
                f"/api/v2/workflows/{workflow_id}/bindings",
                {
                    "source": source,
                    "target_node_id": video_b["node_id"],
                    "input_role": binding.get("input_role"),
                    "required": binding.get("required", False),
                    "enabled": True,
                    "order": index,
                    "label": binding.get("label"),
                    "metadata": binding.get("metadata") or {},
                },
                idempotency_key=stable_idempotency_key(
                    report.run_id, "video-binding", str(binding.get("binding_id")), index
                ),
                etag=etag,
            )
            etag = mutation_headers.get("etag") or etag
        patch_node(
            bgm,
            {
                "parameters": {
                    **(bgm.get("parameters") or {}),
                    "duration_seconds": 30,
                }
            },
        )
        if not nodes_for("editing"):
            created_editing, _ = self.client.post(
                f"/api/v2/workflows/{workflow_id}/nodes",
                {
                    "node_type": "editing",
                    "creative_role": "editing",
                    "title": "Final 30-second Composition",
                    "position": {"x": 1440, "y": 0},
                },
                idempotency_key=stable_idempotency_key(report.run_id, "editing", "all-elements", 0),
                etag=etag,
            )
            workflow = created_editing.get("workflow") or workflow
        workflow, _ = self.client.get(f"/api/v2/workflows/{workflow_id}")
        _assert_distinct_all_elements_segments(workflow)
        return workflow

    def _assert_manual_media(self, report: ProgressiveAcceptanceReport, workflow_id: str) -> None:
        self._record_provider_events(report, workflow_id)
        if report.provider_tasks:
            raise AcceptanceFailure(
                "acceptance_unexpected_provider_execution",
                "Manual media mode submitted a provider task.",
            )

    def _record_provider_events(
        self, report: ProgressiveAcceptanceReport, workflow_id: str
    ) -> None:
        events, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/events?limit=500")
        report._event_snapshot = events
        report.event_cursor = events.get("next_cursor")
        report.provider_tasks = [
            {
                "event_type": item.get("event_type"),
                "node_id": item.get("node_id"),
                "provider_task_id": (item.get("payload") or {}).get("provider_task_id"),
            }
            for item in events.get("items", [])
            if str(item.get("event_type", "")).startswith("provider_task_")
        ]

    def _complete_final_video(
        self, report: ProgressiveAcceptanceReport, workflow: dict[str, Any]
    ) -> None:
        workflow = self._complete_ready_video(report, workflow)
        assert report.workflow_id is not None
        workflow_id = report.workflow_id
        workflow, workflow_headers = self.client.get(f"/api/v2/workflows/{workflow_id}")
        ready_videos = [
            item
            for item in workflow.get("nodes", [])
            if item.get("node_type") == "video" and item.get("status") == "ready"
        ]
        self._record_workflow(report, workflow)
        editing = next(
            (item for item in workflow.get("nodes", []) if item.get("node_type") == "editing"),
            None,
        )
        etag = workflow_headers.get("etag")
        if editing is None:
            if not etag:
                raise AcceptanceFailure(
                    "acceptance_etag_missing", "Workflow ETag is missing for Editing creation."
                )
            created, mutation_headers = self.client.post(
                f"/api/v2/workflows/{workflow_id}/nodes",
                {
                    "node_type": "editing",
                    "creative_role": "editing",
                    "title": "Final Composition",
                    "position": {"x": 0, "y": 0},
                },
                idempotency_key=stable_idempotency_key(report.run_id, "editing", "create", 0),
                etag=etag,
            )
            editing = created.get("node")
            if not isinstance(editing, dict):
                raise AcceptanceFailure(
                    "acceptance_editing_missing", "Editing Node creation returned no Node."
                )
            etag = mutation_headers.get("etag")
        bound_video_ids = {
            str((binding.get("source") or {}).get("source_node_id"))
            for binding in workflow.get("bindings", [])
            if binding.get("target_node_id") == editing["node_id"]
            and binding.get("enabled") is not False
        }
        for index, video in enumerate(ready_videos):
            if str(video["node_id"]) in bound_video_ids:
                continue
            if not etag:
                raise AcceptanceFailure(
                    "acceptance_etag_missing", "Workflow ETag is missing for Editing binding."
                )
            _, mutation_headers = self.client.post(
                f"/api/v2/workflows/{workflow_id}/bindings",
                {
                    "source": {
                        "kind": "node_output",
                        "source_node_id": video["node_id"],
                    },
                    "target_node_id": editing["node_id"],
                    "input_role": "video_reference",
                },
                idempotency_key=stable_idempotency_key(
                    report.run_id, "editing-binding", str(video["node_id"]), index
                ),
                etag=etag,
            )
            etag = mutation_headers.get("etag")
        if self.scenario_name == "all-elements-30s":
            ready_bgm = next(
                (
                    item
                    for item in workflow.get("nodes", [])
                    if item.get("creative_role") == "bgm" and item.get("status") == "ready"
                ),
                None,
            )
            if ready_bgm is None:
                raise AcceptanceFailure(
                    "acceptance_target_incomplete",
                    "The all-elements Editing Export requires a Ready BGM Node.",
                )
            bgm_is_bound = any(
                (binding.get("source") or {}).get("source_node_id") == ready_bgm["node_id"]
                and binding.get("target_node_id") == editing["node_id"]
                and binding.get("enabled") is not False
                for binding in workflow.get("bindings", [])
            )
            if not bgm_is_bound:
                if not etag:
                    raise AcceptanceFailure(
                        "acceptance_etag_missing",
                        "Workflow ETag is missing for Editing BGM binding.",
                    )
                _, mutation_headers = self.client.post(
                    f"/api/v2/workflows/{workflow_id}/bindings",
                    {
                        "source": {
                            "kind": "node_output",
                            "source_node_id": ready_bgm["node_id"],
                        },
                        "target_node_id": editing["node_id"],
                        "input_role": "audio_reference",
                    },
                    idempotency_key=stable_idempotency_key(
                        report.run_id, "editing-binding", str(ready_bgm["node_id"]), 0
                    ),
                    etag=etag,
                )
                etag = mutation_headers.get("etag")
        node_id = str(editing["node_id"])
        detail, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/nodes/{node_id}")
        manifest = (detail.get("structured_content") or {}).get("manifest") or {}
        self.client.post(
            f"/api/v2/workflows/{workflow_id}/nodes/{node_id}/export",
            {
                "expected_manifest_revision": manifest.get("manifest_revision"),
                "availability_policy": "use_ready_inputs",
            },
            idempotency_key=stable_idempotency_key(report.run_id, "export", node_id, 0),
        )
        completed = self._wait_editing(workflow_id, node_id)
        asset_id = completed.get("output_asset_id")
        if not asset_id:
            raise AcceptanceFailure(
                "acceptance_final_media_invalid", "Editing Export has no output Asset."
            )
        final_workflow, _ = self.client.get(f"/api/v2/workflows/{workflow_id}")
        self._record_workflow(report, final_workflow)
        self._record_assets(report, workflow_id)
        asset = next((item for item in report.assets if item["asset_id"] == asset_id), None)
        if not asset or not asset.get("media_url"):
            raise AcceptanceFailure(
                "acceptance_final_media_invalid", "Final Asset has no browser-safe URL."
            )
        content, _ = self.client.bytes(str(asset["media_url"]))
        report._final_media_bytes = content
        report.probe = _probe_bytes(content)
        if self.scenario_name == "all-elements-30s" and not (
            28 <= float(report.probe.get("duration_seconds") or 0) <= 32
            and report.probe.get("width") == 1280
            and report.probe.get("height") == 720
            and report.probe.get("has_audio") is True
            and report.probe.get("video_codec") == "h264"
        ):
            raise AcceptanceFailure(
                "acceptance_final_media_invalid",
                "The all-elements final Asset does not satisfy the 30-second media contract.",
            )
        self._record_provider_events(report, workflow_id)

    def _complete_ready_video(
        self, report: ProgressiveAcceptanceReport, workflow: dict[str, Any]
    ) -> dict[str, Any]:
        assert report.workflow_id is not None
        workflow_id = report.workflow_id
        draft_ids = [
            str(node["node_id"])
            for node in workflow.get("nodes", [])
            if node.get("status") in {"draft", "failed"}
            and node.get("node_type")
            in (
                {"text", "script", "image", "video", "audio"}
                if self.scenario_name == "all-elements-30s"
                else {"image", "video"}
            )
        ]
        if draft_ids:
            retry_failed = any(
                node.get("status") == "failed" and str(node.get("node_id")) in draft_ids
                for node in workflow.get("nodes", [])
            )
            accepted, _ = self.client.post(
                f"/api/v2/workflows/{workflow_id}/runs",
                (
                    {"scope": "all_drafts", "source_action": "global_run"}
                    if self.scenario_name == "all-elements-30s" and not retry_failed
                    else {
                        "scope": "selected_nodes",
                        "node_ids": draft_ids,
                        "source_action": "run_selected",
                        "retry_failed": retry_failed,
                    }
                ),
                idempotency_key=stable_idempotency_key(report.run_id, "run", "media", 0),
            )
            self._wait_runtime(report, workflow_id, str(accepted["execution_id"]))
        workflow, _ = self.client.get(f"/api/v2/workflows/{workflow_id}")
        ready_videos = [
            item
            for item in workflow.get("nodes", [])
            if item.get("node_type") == "video" and item.get("status") == "ready"
        ]
        if not ready_videos:
            raise AcceptanceFailure(
                "acceptance_target_incomplete", "No Ready Video Node was published."
            )
        self._record_workflow(report, workflow)
        runtime, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/runtime")
        report._runtime_snapshot = runtime
        self._record_assets(report, workflow_id)
        self._record_provider_events(report, workflow_id)
        return workflow

    def _record_assets(self, report: ProgressiveAcceptanceReport, workflow_id: str) -> None:
        assets, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/assets")
        report._asset_snapshot = assets
        report.assets = [
            {
                "asset_id": item.get("asset_id"),
                "media_type": item.get("media_type"),
                "status": item.get("status"),
                "media_url": item.get("media_url"),
                "duration_seconds": item.get("duration_seconds"),
                "version_id": item.get("version_id") or item.get("selected_version_id"),
                "width": item.get("width"),
                "height": item.get("height"),
                "has_audio": item.get("has_audio"),
                "provider": item.get("provider"),
                "model_ref": item.get("model_ref") or item.get("model_id"),
            }
            for item in assets.get("assets", [])
        ]

    def _wait_runtime(
        self, report: ProgressiveAcceptanceReport, workflow_id: str, execution_id: str
    ) -> None:
        while True:
            self.bounds.require_time("media execution")
            runtime, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/runtime")
            report._runtime_snapshot = runtime
            active_execution_id = runtime.get("active_execution_id") or runtime.get("execution_id")
            if (
                active_execution_id == execution_id
                and runtime.get("execution_status") in TERMINAL_EXECUTIONS
            ):
                if runtime.get("execution_status") not in {"completed", "partial_failed"}:
                    raise AcceptanceFailure("acceptance_runtime_failed", "Media execution failed.")
                return
            execution_nodes = [
                node
                for node in (runtime.get("node_runtime") or {}).values()
                if node.get("execution_id") == execution_id
            ]
            if active_execution_id is None and execution_nodes:
                visible_statuses = {node.get("visible_status") for node in execution_nodes}
                if visible_statuses <= {"ready", "failed"}:
                    if "ready" not in visible_statuses:
                        raise AcceptanceFailure(
                            "acceptance_runtime_failed", "Media execution failed."
                        )
                    return
            time.sleep(self.poll_interval)

    def _wait_editing(self, workflow_id: str, node_id: str) -> dict[str, Any]:
        while True:
            self.bounds.require_time("Editing Export")
            node, _ = self.client.get(f"/api/v2/workflows/{workflow_id}/nodes/{node_id}")
            active_export = (node.get("structured_content") or {}).get("active_export")
            if node.get("status") in {"ready", "failed"} and active_export is None:
                if node.get("status") != "ready":
                    raise AcceptanceFailure("acceptance_editing_failed", "Editing Export failed.")
                return node
            time.sleep(self.poll_interval)


def _video_draft_ready(workflow: dict[str, Any]) -> bool:
    return any(
        node.get("node_type") == "video"
        and str(node.get("generation_prompt") or "").strip()
        and bool(node.get("structured_content"))
        for node in workflow.get("nodes", [])
    )


def _guidance_complete(timeline: dict[str, Any]) -> bool:
    guidance = timeline.get("guidance_session") or {}
    if guidance.get("status") == "completed":
        return True
    if guidance.get("active_proposal_id"):
        return False
    if any(
        item.get("status") in {"queued", "leased", "running", "waiting"}
        for item in timeline.get("continuations") or []
    ):
        return False
    topics = tuple(item for item in guidance.get("topics") or [] if isinstance(item, dict))
    return bool(topics) and all(
        item.get("status") in {"selected", "deferred", "excluded", "completed"} for item in topics
    )


def _assert_draft_contract(workflow: dict[str, Any]) -> None:
    videos = [node for node in workflow.get("nodes", []) if node.get("node_type") == "video"]
    if not videos:
        raise AcceptanceFailure(
            "acceptance_prompt_incomplete", "The journey did not create a Video Draft."
        )
    for node in videos:
        if not str(node.get("summary_prompt") or "").strip():
            raise AcceptanceFailure(
                "acceptance_prompt_incomplete", "A Video Draft summary prompt is missing."
            )
        if not str(node.get("generation_prompt") or "").strip():
            raise AcceptanceFailure(
                "acceptance_prompt_incomplete", "A Video Draft generation prompt is missing."
            )
        if not isinstance(node.get("structured_content"), dict) or not node.get(
            "structured_content"
        ):
            raise AcceptanceFailure(
                "acceptance_prompt_incomplete", "A Video Draft typed content payload is missing."
            )
        if not isinstance(node.get("parameters", {}), dict):
            raise AcceptanceFailure(
                "acceptance_prompt_incomplete", "A Video Draft parameter payload is invalid."
            )
        if node.get("model_selection_mode") == "explicit" and not node.get("model_ref"):
            raise AcceptanceFailure(
                "acceptance_prompt_incomplete", "An explicit Video model reference is missing."
            )


def _all_elements_storyboard_b_content(
    storyboard_a: dict[str, Any],
) -> dict[str, Any]:
    source_content = storyboard_a.get("structured_content") or {}
    return {
        "sequence_summary": (
            "The curator completes the pour and resolves the tea ritual in a final brand tableau."
        ),
        "narrative_goal": (
            "Advance from anticipation to refreshment, product proof, and a memorable close."
        ),
        "style": source_content.get("style")
        or {
            "style_prompt": "Premium cinematic live-action storyboard illustration",
            "source": "user",
        },
        "panels": [
            {
                "panel_index": 1,
                "beat": "Resume the poised pour from Sequence A's closing state.",
                "composition": "Medium frame preserving bottle, glass, and curator positions.",
                "camera": "Matched eyeline and lens from the prior closing frame.",
                "subject_action": "The curator begins the committed pour.",
                "continuity_from_previous": "Exact handoff from the poised first-pour state.",
            },
            {
                "panel_index": 2,
                "beat": "Sparkling tea arcs cleanly into the tasting glass.",
                "composition": "Product and liquid share the foreground.",
                "camera": "Controlled lateral track.",
                "subject_action": "The curator steadies the bottle while pouring.",
                "continuity_from_previous": "Continue the same pour without resetting props.",
            },
            {
                "panel_index": 3,
                "beat": "Effervescence rises through the filled glass.",
                "composition": "Macro detail with package silhouette retained behind.",
                "camera": "Gentle macro push-in.",
                "subject_action": "Bubbles collect and rise around the tea.",
                "continuity_from_previous": "The completed pour motivates the macro detail.",
            },
            {
                "panel_index": 4,
                "beat": "The tasting cup enters beside the sparkling glass.",
                "composition": "Balanced bottle, glass, and porcelain cup triangle.",
                "camera": "Return to a stable tabletop medium shot.",
                "subject_action": "The curator places the cup with deliberate precision.",
                "continuity_from_previous": "Retain liquid level and package orientation.",
            },
            {
                "panel_index": 5,
                "beat": "The curator presents the finished serving ritual.",
                "composition": "Curator framed behind the complete product arrangement.",
                "camera": "Subtle forward drift.",
                "subject_action": "An open hand invites attention to the serving.",
                "continuity_from_previous": "All table objects remain fixed.",
            },
            {
                "panel_index": 6,
                "beat": "Dawn light catches condensation and gold package details.",
                "composition": "Three-quarter product beauty angle.",
                "camera": "Slow arc around the bottle shoulder.",
                "subject_action": "Condensation and highlights reveal material quality.",
                "continuity_from_previous": "Preserve the completed serving arrangement.",
            },
            {
                "panel_index": 7,
                "beat": "The curator withdraws to give the product full focus.",
                "composition": "Bottle and glass dominate while the curator recedes.",
                "camera": "Measured rack focus to the label plane.",
                "subject_action": "The curator settles into a calm background pose.",
                "continuity_from_previous": "Continue the same camera arc into the focus shift.",
            },
            {
                "panel_index": 8,
                "beat": "The bottle and sparkling glass lock into the hero arrangement.",
                "composition": "Centered final product tableau with clean negative space.",
                "camera": "Finish the push-in and stabilize.",
                "subject_action": "Fine bubbles and dawn reflections remain active.",
                "continuity_from_previous": "Hold established package geometry and liquid level.",
            },
            {
                "panel_index": 9,
                "beat": "Resolve on the final bottle-and-glass brand beat.",
                "composition": "Readable hero pack shot against the rooftop tea bar.",
                "camera": "Locked final frame.",
                "subject_action": "The complete serving rests in a confident final state.",
                "continuity_from_previous": "Settle from motion without changing identity or layout.",
            },
        ],
        "no_generated_text": True,
    }


def _all_elements_video_b_content() -> dict[str, Any]:
    return {
        "segment_summary": (
            "The curator completes the sparkling pour and resolves the ritual in a final "
            "bottle-and-glass brand tableau."
        ),
        "duration_seconds": 15,
        "storyboard_content": (
            "Open on Sequence A's exact poised-pour closing state. Complete the pour, move "
            "through effervescence and tasting-cup presentation, then push into the stable "
            "bottle-and-glass final brand beat."
        ),
        "dialogue": "",
        "voice_style": "",
        "environment_sound": "Quiet rooftop ambience and soft porcelain contact",
        "action_effects": "Bottle pour, sparkling fizz, and glass placement",
        "negative_constraints": "No embedded background music and no repeated establishing move.",
        "background_music": False,
    }


def _assert_distinct_all_elements_segments(workflow: dict[str, Any]) -> None:
    def nodes_for(role: str) -> list[dict[str, Any]]:
        return [node for node in workflow.get("nodes") or [] if node.get("creative_role") == role]

    def normalized_content(node: dict[str, Any]) -> str:
        content = dict(node.get("structured_content") or {})
        content.pop("duration_seconds", None)
        return json.dumps(content, sort_keys=True, separators=(",", ":"))

    storyboards = nodes_for("storyboard_sequence")
    videos = nodes_for("storyboard_video")
    if len(storyboards) != 2 or len(videos) != 2:
        raise AcceptanceFailure(
            "acceptance_segment_continuity_invalid",
            "The all-elements scenario requires two Storyboard and two Video segments.",
        )
    for earlier, later in ((storyboards[0], storyboards[1]), (videos[0], videos[1])):
        summaries_are_distinct = (
            str(earlier.get("summary_prompt") or "").strip().casefold()
            != str(later.get("summary_prompt") or "").strip().casefold()
        )
        prompts_are_distinct = (
            str(earlier.get("generation_prompt") or "").strip().casefold()
            != str(later.get("generation_prompt") or "").strip().casefold()
        )
        content_is_distinct = normalized_content(earlier) != normalized_content(later)
        if not (summaries_are_distinct and prompts_are_distinct and content_is_distinct):
            raise AcceptanceFailure(
                "acceptance_segment_continuity_invalid",
                "Segment B must advance a distinct narrative responsibility before provider work.",
            )


def _assert_scenario_constraints(
    workflow: dict[str, Any],
    timeline: dict[str, Any],
    *,
    through: JourneyTarget,
    scenario_name: ScenarioName = "standard",
) -> None:
    guidance = timeline.get("guidance_session") or {}
    decisions = {
        str(item.get("element_kind")): item.get("presence")
        for item in guidance.get("element_decisions") or []
    }
    explicit_constraints = (guidance.get("goal") or {}).get("explicit_constraints") or {}
    if scenario_name == "all-elements-30s":
        expected_included = {
            "world_setting",
            "product",
            "prop",
            "character",
            "scene",
            "script",
            "storyboard",
            "video",
            "audio",
        }
        expected_excluded: set[str] = set()
    else:
        expected_included = {"product", "scene", "storyboard", "video"}
        expected_excluded = {"prop", "audio"}
    if scenario_name != "all-elements-30s":
        if through == "video-draft":
            expected_included.add("character")
        else:
            expected_excluded.add("character")
    raw_exclusions = explicit_constraints.get("exclude_kinds")
    explicit_exclusions = (
        {str(item) for item in raw_exclusions if isinstance(item, str)}
        if isinstance(raw_exclusions, (list, tuple, set))
        else set()
    )
    excluded = {
        kind
        for kind in expected_excluded
        if decisions.get(kind) == "exclude"
        or explicit_constraints.get(kind) == "exclude"
        or kind in explicit_exclusions
    }
    if any(decisions.get(kind) != "include" for kind in expected_included) or (
        excluded != expected_excluded
    ):
        raise AcceptanceFailure(
            "acceptance_constraint_mismatch",
            "Guidance decisions do not preserve the scenario element constraints.",
        )

    videos = [item for item in workflow.get("nodes", []) if item.get("node_type") == "video"]
    required_video_parameters = explicit_constraints.get("required_video_parameters")
    if not isinstance(required_video_parameters, dict):
        required_video_parameters = {}
    for video in videos:
        parameters = video.get("parameters") or {}
        structured = video.get("structured_content") or {}
        duration = parameters.get("duration_seconds", structured.get("duration_seconds"))
        aspect_ratio = parameters.get("aspect_ratio")
        explicit_aspect_ratio = explicit_constraints.get(
            "aspect_ratio", required_video_parameters.get("aspect_ratio")
        )
        invalid_geometry = (
            duration != (15 if scenario_name == "all-elements-30s" else 5) or aspect_ratio != "16:9"
            if through == "final-video"
            else (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or duration <= 0
                or aspect_ratio not in {None, "16:9"}
                or (aspect_ratio is None and explicit_aspect_ratio != "16:9")
            )
        )
        if invalid_geometry:
            raise AcceptanceFailure(
                "acceptance_constraint_mismatch",
                "Video Draft duration or aspect ratio does not preserve the scenario.",
            )
        if any("bgm" in str(key).lower() and bool(value) for key, value in parameters.items()):
            raise AcceptanceFailure(
                "acceptance_constraint_mismatch",
                "Video Draft parameters incorrectly include BGM generation.",
            )
    if expected_excluded.intersection({"audio"}) and any(
        item.get("node_type") == "audio" for item in workflow.get("nodes", [])
    ):
        raise AcceptanceFailure(
            "acceptance_constraint_mismatch",
            "The scenario excluded BGM but an Audio Node was materialized.",
        )

    if scenario_name == "all-elements-30s":
        nodes = list(workflow.get("nodes") or [])
        expected_counts = {
            "world_setting": 1,
            "product": 1,
            "prop": 1,
            "character": 2,
            "scene": 1,
            "script": 1,
            "storyboard_sequence": 2,
            "storyboard_video": 2,
            "bgm": 1,
            "editing": 1,
        }
        actual_counts = {
            role: sum(node.get("creative_role") == role for node in nodes)
            for role in expected_counts
        }
        character_nodes = [node for node in nodes if node.get("creative_role") == "character"]
        character_kinds = {
            (node.get("structured_content") or {}).get("character_asset_kind")
            for node in character_nodes
        }
        pair_ids = {
            (node.get("metadata") or {}).get("character_pair_id") for node in character_nodes
        }
        main = next(
            (
                node
                for node in character_nodes
                if (node.get("structured_content") or {}).get("character_asset_kind")
                == "identity_master"
            ),
            None,
        )
        turnaround = next(
            (
                node
                for node in character_nodes
                if (node.get("structured_content") or {}).get("character_asset_kind")
                == "turnaround"
            ),
            None,
        )
        has_pair_binding = any(
            binding.get("enabled") is not False
            and binding.get("required") is True
            and (binding.get("source") or {}).get("source_node_id") == (main or {}).get("node_id")
            and binding.get("target_node_id") == (turnaround or {}).get("node_id")
            for binding in workflow.get("bindings") or []
        )
        bgm = next((node for node in nodes if node.get("creative_role") == "bgm"), None)
        nodes_by_id = {str(node.get("node_id")): node for node in nodes}
        enabled_bindings = [
            binding
            for binding in workflow.get("bindings") or []
            if binding.get("enabled") is not False
        ]
        storyboards = [node for node in nodes if node.get("creative_role") == "storyboard_sequence"]
        videos = [node for node in nodes if node.get("creative_role") == "storyboard_video"]

        def bound_sources(target_node_id: str) -> list[dict[str, Any]]:
            return [
                nodes_by_id[str((binding.get("source") or {}).get("source_node_id"))]
                for binding in enabled_bindings
                if binding.get("target_node_id") == target_node_id
                and str((binding.get("source") or {}).get("source_node_id")) in nodes_by_id
            ]

        required_visual_roles = {"product", "prop", "character", "scene"}
        storyboard_sources_are_complete = all(
            required_visual_roles.issubset(
                {source.get("creative_role") for source in bound_sources(node["node_id"])}
            )
            and all(
                (source.get("structured_content") or {}).get("character_asset_kind")
                != "identity_master"
                for source in bound_sources(node["node_id"])
                if source.get("creative_role") == "character"
            )
            for node in storyboards
        )
        video_storyboard_ids: list[str] = []
        video_sources_are_complete = True
        for node in videos:
            sources = bound_sources(node["node_id"])
            storyboard_sources = [
                source for source in sources if source.get("creative_role") == "storyboard_sequence"
            ]
            video_sources_are_complete = video_sources_are_complete and (
                len(storyboard_sources) == 1
                and required_visual_roles.issubset(
                    {source.get("creative_role") for source in sources}
                )
                and all(
                    (source.get("structured_content") or {}).get("character_asset_kind")
                    != "identity_master"
                    for source in sources
                    if source.get("creative_role") == "character"
                )
            )
            video_storyboard_ids.extend(str(source["node_id"]) for source in storyboard_sources)
        if (
            actual_counts != expected_counts
            or character_kinds != {"identity_master", "turnaround"}
            or len(pair_ids) != 1
            or None in pair_ids
            or not has_pair_binding
            or (bgm or {}).get("parameters", {}).get("duration_seconds") != 30
            or not storyboard_sources_are_complete
            or not video_sources_are_complete
            or len(set(video_storyboard_ids)) != 2
        ):
            raise AcceptanceFailure(
                "acceptance_constraint_mismatch",
                "The all-elements scenario graph is incomplete or inconsistent.",
            )


def _scenario_prompt(
    through: JourneyTarget,
    decision_mode: DecisionMode,
    *,
    scenario_name: ScenarioName = "standard",
) -> str:
    if scenario_name == "all-elements-30s":
        authority = (
            "Present public options and wait for my explicit choice."
            if decision_mode == "user"
            else "Present public options and let the Agent recommend each choice."
        )
        return (
            "Create a 30-second 16:9 720p premium cinematic live action advertisement for "
            "a fictional cold-brew sparkling green tea in a near-future glass rooftop "
            "teahouse at dawn. Include World Setting, one Product bottle, one porcelain "
            "tasting-cup Prop, one human tea-curator Character, one Scene, one Script, two "
            "Storyboard sequences, two 15-second Video segments in order, and one 30-second "
            "instrumental BGM. Character Main and Turnaround references must remain detailed "
            "semi-realistic illustrations. Videos must contain dialogue-free ambience and "
            "physical effects but no embedded BGM. Preserve duration_seconds=15 and "
            f"aspect_ratio=16:9 on each Video. {authority} Do not generate media yet."
        )
    if through == "final-video":
        return (
            "Create a five-second 16:9 fictional bottled-tea advertisement with one Product, "
            "one Scene, one Storyboard grid, one Video segment, and Editing. The Video Draft "
            "must explicitly preserve duration_seconds=5 and aspect_ratio=16:9 in its "
            "parameters. Exclude World Setting, Prop, Character, and BGM. Recommend the "
            "creative options."
        )
    authority = (
        "Present public options and wait for my explicit choice."
        if decision_mode == "user"
        else "Present public options and let the Agent recommend each choice."
    )
    return (
        "Create a concise 16:9 advertising video plan with Product, Character, Scene, "
        "Storyboard, and a complete Video Draft. The Video Draft must explicitly preserve "
        "aspect_ratio=16:9 in its parameters. Exclude World Setting, Prop, and BGM. "
        f"{authority} Do not generate media yet."
    )


def _probe_bytes(content: bytes) -> dict[str, Any]:
    facts = _probe_media_bytes(content, suffix=".mp4")
    if float(facts.get("duration_seconds") or 0) <= 0 or not facts.get("has_video"):
        raise AcceptanceFailure("acceptance_final_media_invalid", "Final media probe is invalid.")
    return facts


def _probe_media_url(
    client: ProgressiveJourneyClient,
    url: str,
    media_type: str,
) -> dict[str, Any]:
    content, _ = client.bytes(url)
    if media_type == "video":
        return _probe_bytes(content)
    suffix = ".jpg" if media_type == "image" else ".bin"
    return _probe_media_bytes(content, suffix=suffix)


def _probe_media_bytes(content: bytes, *, suffix: str) -> dict[str, Any]:
    path = Path("/tmp") / f"adcraft-progressive-{uuid4().hex}{suffix}"
    try:
        path.write_bytes(content)
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(completed.stdout)
        duration = float((payload.get("format") or {}).get("duration") or 0)
        video = next(
            (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
            None,
        )
        if not video:
            raise AcceptanceFailure(
                "acceptance_final_media_invalid", "Media probe found no visual stream."
            )
        audio = next(
            (item for item in payload.get("streams", []) if item.get("codec_type") == "audio"),
            None,
        )
        facts: dict[str, Any] = {
            "width": video.get("width"),
            "height": video.get("height"),
            "has_video": True,
            "has_audio": audio is not None,
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name") if audio else None,
        }
        if duration > 0:
            facts["duration_seconds"] = duration
        return facts
    finally:
        path.unlink(missing_ok=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--decision-mode", choices=("user", "agent-recommended"), required=True)
    parser.add_argument(
        "--scenario",
        choices=("standard", "all-elements-30s"),
        default="standard",
    )
    parser.add_argument(
        "--target",
        choices=("video_draft", "ready_video", "final_export"),
        required=True,
    )
    parser.add_argument(
        "--require-guidance-complete",
        action=argparse.BooleanOptionalAction,
        required=True,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/v2/acceptance"),
    )
    parser.add_argument("--parent-run-id")
    parser.add_argument(
        "--creative-review",
        type=Path,
        help="Optional CreativeReviewV2 JSON supplied after human review.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--workflow-id",
        help="Resume an acceptance Workflow without resubmitting its initial turn.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    started = time.monotonic()
    run_id = f"progressive_{uuid4().hex[:16]}"
    through: JourneyTarget = "video-draft" if args.target == "video_draft" else "final-video"
    report = ProgressiveAcceptanceReport(
        run_id=run_id,
        scenario_id=(
            args.scenario
            if args.scenario == "all-elements-30s"
            else f"{args.decision_mode}-{args.target}"
        ),
        decision_mode=args.decision_mode,
        through=through,
    )
    scenario = _acceptance_scenario(
        target=args.target,
        require_guidance_complete=args.require_guidance_complete,
        scenario_name=args.scenario,
    )
    review = (
        CreativeReviewV2.model_validate_json(args.creative_review.read_text(encoding="utf-8"))
        if args.creative_review
        else CreativeReviewV2(status="pending")
    )
    client = ProgressiveJourneyClient(args.base_url)
    try:
        ProgressiveJourneyDriver(
            client,
            decision_mode=args.decision_mode,
            through=through,
            timeout_seconds=args.timeout_seconds,
            resume_workflow_id=args.workflow_id,
            acceptance_target=args.target,
            require_guidance_complete=args.require_guidance_complete,
            scenario_name=args.scenario,
        ).run(report)
        report.status = "completed"
        return_code = 0
    except (AcceptanceFailure, httpx.HTTPError) as error:
        report.status = "blocked" if getattr(error, "blocked", False) else "failed"
        report.error = {
            "code": getattr(error, "code", "acceptance_transport_failed"),
            "message": str(error),
        }
        return_code = 2
    finally:
        report.duration_seconds = round(time.monotonic() - started, 3)
        workflow = report._workflow_snapshot or {
            "workflow_id": report.workflow_id or "unassigned",
            "project_id": report.project_id,
            "nodes": [],
            "bindings": [],
        }
        evidence = (
            ProgressiveAcceptanceEvidenceCollector()
            .collect(
                workflow=workflow,
                timeline=report._timeline_snapshot,
                runtime=report._runtime_snapshot,
                events=report._event_snapshot,
                assets=report._asset_snapshot,
                media_probe_cache=ProgressiveMediaProbeCache(
                    lambda url, media_type: _probe_media_url(client, url, media_type)
                ),
            )
            .model_copy(
                update={
                    "diagnostics": {
                        "driver_status": report.status,
                        "driver_error": report.error,
                        "decision_count": len(report.decisions),
                        "scenario_id": report.scenario_id,
                        "decisions": report.decisions,
                        "provider_tasks": report.provider_tasks,
                        "final_media_probe": report.probe,
                        "elapsed_seconds": report.duration_seconds,
                    }
                }
            )
        )
        evaluated = ProgressiveAcceptanceEvaluator().evaluate(
            scenario,
            evidence,
            creative_review=review,
            acceptance_run_id=run_id,
            parent_run_id=args.parent_run_id,
            attempt_elapsed_seconds=report.duration_seconds,
        )
        report_path = ProgressiveAcceptanceReportStore(args.output_root).append(
            scenario,
            evaluated,
        )
        if report._final_media_bytes is not None:
            _write_final_media_evidence(report_path.parent, report._final_media_bytes)
        if evaluated.technical_verdict == "fail":
            return_code = 2
        print(
            json.dumps(
                {
                    "technical_verdict": evaluated.technical_verdict,
                    "creative_review": evaluated.creative_review.status,
                    "report": str(report_path),
                }
            )
        )
        client.close()
    return return_code


def _write_final_media_evidence(run_dir: Path, content: bytes) -> None:
    media_path = run_dir / "final-export.mp4"
    media_path.write_bytes(content)
    frames_dir = run_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-vf",
            "fps=1/10",
            "-frames:v",
            "3",
            str(frames_dir / "frame-%02d.jpg"),
        ],
        check=True,
    )


def _acceptance_scenario(
    *,
    target: AcceptanceTarget,
    require_guidance_complete: bool,
    scenario_name: ScenarioName = "standard",
) -> ProgressiveAcceptanceScenarioV2:
    if scenario_name == "all-elements-30s":
        return ProgressiveAcceptanceScenarioV2(
            scenario_name=scenario_name,
            target=target,
            require_guidance_complete=require_guidance_complete,
            expected_creative_roles=(
                "world_setting",
                "product",
                "prop",
                "character",
                "scene",
                "script",
                "storyboard_sequence",
                "storyboard_video",
                "bgm",
                "editing",
            ),
            expected_role_counts={
                "world_setting": 1,
                "product": 1,
                "prop": 1,
                "character": 2,
                "scene": 1,
                "script": 1,
                "storyboard_sequence": 2,
                "storyboard_video": 2,
                "bgm": 1,
                "editing": 1,
            },
            required_relationships=(
                AcceptanceRelationshipV2(
                    source_role="character",
                    target_role="storyboard_sequence",
                    input_role="image_reference",
                ),
                AcceptanceRelationshipV2(
                    source_role="storyboard_sequence",
                    target_role="storyboard_video",
                    input_role="image_reference",
                ),
                AcceptanceRelationshipV2(
                    source_role="storyboard_video",
                    target_role="editing",
                    input_role="video_reference",
                    require_provider_delivery=False,
                ),
                AcceptanceRelationshipV2(
                    source_role="bgm",
                    target_role="editing",
                    input_role="audio_reference",
                    require_provider_delivery=False,
                ),
            ),
            requested_parameters={
                "aspect_ratio": "16:9",
                "duration_seconds": 15,
                "final_duration_seconds": 30,
            },
            audio_policy="full",
        )
    expected_roles = ["product", "scene", "storyboard_sequence", "storyboard_video"]
    relationships = [
        AcceptanceRelationshipV2(
            source_role="product",
            target_role="storyboard_sequence",
            input_role="image_reference",
        ),
        AcceptanceRelationshipV2(
            source_role="scene",
            target_role="storyboard_sequence",
            input_role="image_reference",
        ),
        AcceptanceRelationshipV2(
            source_role="storyboard_sequence",
            target_role="storyboard_video",
            input_role="image_reference",
        ),
    ]
    if target == "final_export":
        expected_roles.append("editing")
        relationships.append(
            AcceptanceRelationshipV2(
                source_role="storyboard_video",
                target_role="editing",
                input_role="video_reference",
                require_provider_delivery=False,
            )
        )
    return ProgressiveAcceptanceScenarioV2(
        target=target,
        require_guidance_complete=require_guidance_complete,
        expected_creative_roles=tuple(expected_roles),
        required_relationships=tuple(relationships),
        requested_parameters={"aspect_ratio": "16:9", "duration_seconds": 5},
        audio_policy="no_bgm",
    )


if __name__ == "__main__":
    raise SystemExit(main())
