import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.quality_review import (
    NodeQualitySummary,
    QualityIssue,
    WorkflowQualityReviewResponse,
)
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_asset_contract import (
    STRUCTURED_OUTPUT_ASSET_CONTAINER_KEYS,
    canonical_output_assets,
)
from app.services.workflow_graph import update_graph_node_from_run_result
from app.services.workflow_node_identity import (
    ResolvedNodeIdentity,
    WorkflowNodeIdentityError,
    resolve_node_identity,
)
from app.services.workflow_state import resolve_active_result


SUPPORTED_QUALITY_REVIEW_NODES = {
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
}

REVIEWER_RULE_BASED = "rule_based"
ALLOWED_NO_SCENE_REASONS = {
    "product_packshot",
    "title_card",
    "abstract_visual",
    "transition",
    "user_requested_scene_free_shot",
}


class WorkflowQualityReviewError(ValueError):
    """Raised when a node cannot be quality reviewed from persisted state."""


class WorkflowQualityReviewService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def review_node_output(
        self,
        workflow_id: str,
        node_id: str,
        node_type: str,
        output: dict[str, Any],
        output_assets: list[dict[str, Any]],
        input_context: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], NodeQualitySummary]:
        started_at = utc_now()
        started_counter = perf_counter()
        error: str | None = None
        try:
            reviewed_assets, summary = self.rule_based_review(
                workflow_id,
                node_id,
                node_type,
                output,
                output_assets,
                input_context,
            )
            reviewed_output = _sync_quality_assets(dict(output), reviewed_assets)
            reviewed_output["quality_summary"] = summary.model_dump(mode="json")
            return reviewed_output, reviewed_assets, summary
        except Exception as exc:  # noqa: BLE001 - quality review must not fail node runs.
            error = str(exc) or type(exc).__name__
            summary = _summary_from_status(
                "unavailable",
                reviewer=REVIEWER_RULE_BASED,
                issues=[
                    _issue(
                        "quality_review_unavailable",
                        "warning",
                        "Quality review failed internally and was marked unavailable.",
                        details={"error": error},
                    )
                ],
            )
            reviewed_assets = [
                _with_asset_review(asset, "unavailable", summary.issues) for asset in output_assets
            ]
            reviewed_output = _sync_quality_assets(dict(output), reviewed_assets)
            reviewed_output["quality_summary"] = summary.model_dump(mode="json")
            return reviewed_output, reviewed_assets, summary
        finally:
            self._trace_quality_review(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node_type,
                output_assets=locals().get("reviewed_assets", output_assets),
                summary=locals().get("summary"),
                started_at=started_at,
                duration_ms=round((perf_counter() - started_counter) * 1000),
                error=error,
            )

    def rule_based_review(
        self,
        workflow_id: str,
        node_id: str,
        node_type: str,
        output: dict[str, Any],
        output_assets: list[dict[str, Any]],
        input_context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], NodeQualitySummary]:
        del workflow_id, node_id
        assets = [dict(asset) for asset in dedupe_output_assets(output_assets)]
        if node_type not in SUPPORTED_QUALITY_REVIEW_NODES:
            summary = _summary_from_status(
                "unavailable",
                reviewer=REVIEWER_RULE_BASED,
                issues=[
                    _issue(
                        "quality_review_unsupported_node",
                        "info",
                        f"Quality review is not supported for node_type={node_type}.",
                    )
                ],
            )
            return assets, summary
        if not assets:
            summary = _summary_from_status(
                "failed",
                reviewer=REVIEWER_RULE_BASED,
                issues=[
                    _issue(
                        "missing_output_assets",
                        "error",
                        f"{node_type} produced no output assets to review.",
                    )
                ],
            )
            return [], summary

        reviewed_assets = [
            self._review_asset(node_type, asset, output, input_context) for asset in assets
        ]
        summary = _summary_from_assets(reviewed_assets)
        return reviewed_assets, summary

    def visual_review(
        self,
        workflow_id: str,
        node_id: str,
        node_type: str,
        output: dict[str, Any],
        output_assets: list[dict[str, Any]],
        input_context: dict[str, Any],
    ) -> NodeQualitySummary:
        del workflow_id, node_id, node_type, output, output_assets, input_context
        return _summary_from_status(
            "unavailable",
            reviewer="visual_model",
            issues=[
                _issue(
                    "visual_review_not_configured",
                    "info",
                    "Visual quality review is not configured in this backend.",
                )
            ],
        )

    def review_existing_node(
        self,
        workflow_id: str,
        node_id: str,
    ) -> WorkflowQualityReviewResponse:
        identity = self._resolve_identity(workflow_id, node_id)
        active = resolve_active_result(
            self._settings.media_data_dir,
            workflow_id,
            identity.node_id,
            identity.node_type,
        )
        if active is None:
            raise WorkflowQualityReviewError(f"node result not found: {identity.node_id}")

        output = active.get("output") if isinstance(active.get("output"), dict) else {}
        output_assets = (
            active.get("output_assets") if isinstance(active.get("output_assets"), list) else []
        )
        input_context = (
            active.get("input_context") if isinstance(active.get("input_context"), dict) else {}
        )
        reviewed_output, reviewed_assets, summary = self.review_node_output(
            workflow_id,
            identity.node_id,
            identity.node_type,
            output,
            [asset for asset in output_assets if isinstance(asset, dict)],
            input_context,
        )
        updated = {
            **active,
            "node_id": identity.node_id,
            "node_type": identity.node_type,
            "output": reviewed_output,
            "output_assets": reviewed_assets,
        }
        trace_payload = updated.get("trace")
        if isinstance(trace_payload, dict):
            trace_payload["output"] = reviewed_output
            trace_payload["output_assets"] = reviewed_assets
        self._persist_active_payload(workflow_id, identity.node_id, updated)
        update_graph_node_from_run_result(
            data_dir=self._settings.media_data_dir,
            workflow_id=workflow_id,
            node_id=identity.node_id,
            result=updated,
        )
        return WorkflowQualityReviewResponse(
            workflow_id=workflow_id,
            node_id=identity.node_id,
            node_type=identity.node_type,
            quality_summary=summary,
            assets=reviewed_assets,
        )

    def _resolve_identity(self, workflow_id: str, node_id: str) -> ResolvedNodeIdentity:
        try:
            return resolve_node_identity(
                data_dir=self._settings.media_data_dir,
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=None,
            )
        except WorkflowNodeIdentityError as exc:
            active = resolve_active_result(
                self._settings.media_data_dir,
                workflow_id,
                node_id,
            )
            if active is None:
                raise exc
            return ResolvedNodeIdentity(
                workflow_id=workflow_id,
                node_id=str(active.get("node_id") or node_id),
                node_type=str(active.get("node_type") or node_id),
                graph_node=None,
                legacy_node_type_fallback=False,
            )

    def _review_asset(
        self,
        node_type: str,
        asset: dict[str, Any],
        output: dict[str, Any],
        input_context: dict[str, Any],
    ) -> dict[str, Any]:
        issues = _common_asset_issues(node_type, asset)
        if node_type == "character-generation":
            issues.extend(_character_asset_issues(asset))
        elif node_type == "scene-generation":
            issues.extend(_scene_asset_issues(asset, output, input_context))
        elif node_type == "storyboard":
            issues.extend(_storyboard_asset_issues(asset, output, input_context))
        elif node_type == "storyboard-video-generation":
            issues.extend(_storyboard_video_asset_issues(asset))
        status = _status_from_issues(issues)
        return _with_asset_review(asset, status, issues)

    def _trace_quality_review(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_type: str,
        output_assets: list[dict[str, Any]],
        summary: NodeQualitySummary | None,
        started_at: Any,
        duration_ms: int,
        error: str | None,
    ) -> None:
        summary_payload = summary.model_dump(mode="json") if summary else {}
        issues = summary_payload.get("issues", []) if isinstance(summary_payload, dict) else []
        AgentTraceWriter(self._settings.media_data_dir, workflow_id).append(
            agent="Quality Review",
            model=None,
            prompt=f"Rule-based quality review for {node_type}.",
            output=summary_payload,
            error=error,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=duration_ms,
            metadata={
                "trace_role": "quality_review",
                "node_id": node_id,
                "node_type": node_type,
                "reviewer": REVIEWER_RULE_BASED,
                "asset_ids": [
                    str(asset.get("asset_id"))
                    for asset in output_assets
                    if isinstance(asset, dict) and asset.get("asset_id")
                ],
                "summary": summary_payload,
                "issues": issues,
            },
        )

    def _persist_active_payload(
        self,
        workflow_id: str,
        node_id: str,
        payload: dict[str, Any],
    ) -> None:
        node_dir = self._settings.media_data_dir / "runs" / workflow_id / "nodes" / node_id
        _write_json_atomic(node_dir / "active.json", payload)
        trace_path = payload.get("trace_path") or payload.get("metadata_path")
        if isinstance(trace_path, str) and trace_path:
            run_path = self._settings.media_data_dir / trace_path
            if run_path.exists():
                _write_json_atomic(run_path, payload)


def _common_asset_issues(node_type: str, asset: dict[str, Any]) -> list[QualityIssue]:
    asset_id = _asset_id(asset)
    issues: list[QualityIssue] = []
    if not asset_id:
        issues.append(
            _issue("missing_asset_id", "warning", "Asset has no asset_id.", asset_id=None)
        )
    asset_type = str(asset.get("asset_type") or asset.get("type") or asset.get("media_type") or "")
    if not asset_type:
        issues.append(_issue("missing_asset_type", "warning", "Asset has no asset_type.", asset_id))
    expected_type = _expected_asset_type(node_type)
    if expected_type and asset_type and asset_type != expected_type:
        issues.append(
            _issue(
                "asset_type_mismatch",
                "warning",
                f"Expected asset_type={expected_type}, got {asset_type}.",
                asset_id,
            )
        )
    if not _has_preview_source(asset):
        issues.append(
            _issue(
                "missing_preview_source",
                "warning",
                "Asset has no local_path, public_url, remote_url, url, or metadata_path.",
                asset_id,
            )
        )
    if not (asset.get("source_node_id") or asset.get("source_node")):
        issues.append(
            _issue("missing_source_node", "warning", "Asset has no source node metadata.", asset_id)
        )
    if _asset_failed(asset):
        issues.append(
            _issue(
                "asset_generation_failed",
                "error",
                "Asset status indicates generation or download failed.",
                asset_id,
            )
        )
    if _semantic_type_required(node_type) and not asset.get("semantic_type"):
        issues.append(
            _issue("missing_semantic_type", "warning", "Asset has no semantic_type.", asset_id)
        )
    if _entity_id_required(node_type, asset):
        issues.append(
            _issue("missing_entity_id", "warning", "Asset has no stable entity_id.", asset_id)
        )
    return issues


def _character_asset_issues(asset: dict[str, Any]) -> list[QualityIssue]:
    asset_id = _asset_id(asset)
    issues: list[QualityIssue] = []
    if _asset_type(asset) != "image":
        issues.append(
            _issue(
                "character_asset_not_image",
                "warning",
                "Character asset is not image-like.",
                asset_id,
            )
        )
    if not (asset.get("role") or asset.get("character_id") or asset.get("character_name")):
        issues.append(
            _issue(
                "missing_character_metadata",
                "warning",
                "Character asset has no role or character metadata.",
                asset_id,
            )
        )
    return issues


def _scene_asset_issues(
    asset: dict[str, Any],
    output: dict[str, Any],
    input_context: dict[str, Any],
) -> list[QualityIssue]:
    asset_id = _asset_id(asset)
    issues: list[QualityIssue] = []
    entity_id = str(asset.get("entity_id") or "")
    if entity_id and not re.match(r"^scene-reference-\d+$", entity_id):
        issues.append(
            _issue(
                "unstable_scene_entity_id",
                "warning",
                "Scene entity_id should use a stable scene-reference-N id when possible.",
                asset_id,
            )
        )
    if _expected_scene_count(output, input_context) > 1 and len(_assets_from_output(output)) <= 1:
        issues.append(
            _issue(
                "single_scene_reference_for_multi_shot",
                "warning",
                "Multi-shot context has only one scene reference asset.",
                asset_id,
            )
        )
    return issues


def _storyboard_asset_issues(
    asset: dict[str, Any],
    output: dict[str, Any],
    input_context: dict[str, Any],
) -> list[QualityIssue]:
    asset_id = _asset_id(asset)
    issues: list[QualityIssue] = []
    if not _has_storyboard_scene_binding(asset):
        issues.append(
            _issue(
                "missing_scene_binding",
                "warning",
                "Storyboard image has no primary_scene_id, scene_reference_ids, or allowed no_scene_reason.",
                asset_id,
            )
        )
    input_asset_ids = asset.get("input_asset_ids")
    if not isinstance(input_asset_ids, list) or not input_asset_ids:
        issues.append(
            _issue(
                "missing_input_asset_ids",
                "warning",
                "Storyboard image has no shot-level input_asset_ids.",
                asset_id,
            )
        )
    if _storyboard_scene_count(output, input_context) > 1 and len(_assets_from_output(output)) <= 1:
        issues.append(
            _issue(
                "collapsed_storyboard_assets",
                "warning",
                "Multi-shot storyboard context produced only one storyboard image asset.",
                asset_id,
            )
        )
    return issues


def _has_storyboard_scene_binding(asset: dict[str, Any]) -> bool:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    bindings = metadata.get("reference_bindings") if isinstance(metadata, dict) else {}
    bindings = bindings if isinstance(bindings, dict) else {}
    scene_reference_ids = asset.get("scene_reference_ids") or bindings.get("scene_reference_ids")
    no_scene_reason = str(asset.get("no_scene_reason") or bindings.get("no_scene_reason") or "")
    return bool(
        asset.get("primary_scene_id")
        or bindings.get("primary_scene_id")
        or (isinstance(scene_reference_ids, list) and scene_reference_ids)
        or no_scene_reason in ALLOWED_NO_SCENE_REASONS
        or asset.get("scene_id")
        or asset.get("source_scene_order")
        or asset.get("order")
    )


def _storyboard_video_asset_issues(asset: dict[str, Any]) -> list[QualityIssue]:
    asset_id = _asset_id(asset)
    issues: list[QualityIssue] = []
    if not (
        asset.get("source_scene_order")
        or asset.get("source_storyboard_image")
        or asset.get("source_assets")
        or asset.get("input_asset_ids")
    ):
        issues.append(
            _issue(
                "missing_segment_source",
                "warning",
                "Video segment has no source scene, storyboard image, or source asset metadata.",
                asset_id,
            )
        )
    if not _segment_is_ready(asset):
        issues.append(
            _issue(
                "video_segment_not_ready",
                "warning",
                "Video segment is not ready/downloaded yet; quality cannot be passed.",
                asset_id,
            )
        )
    return issues


def _with_asset_review(
    asset: dict[str, Any],
    status: str,
    issues: list[QualityIssue],
) -> dict[str, Any]:
    reviewed = dict(asset)
    reviewed["quality_status"] = status
    reviewed["quality_score"] = _score_for_status(status)
    reviewed["quality_issues"] = [issue.model_dump(mode="json") for issue in issues]
    reviewed["quality_warnings"] = [
        issue.message for issue in issues if issue.severity == "warning"
    ]
    reviewed["reviewer"] = REVIEWER_RULE_BASED
    return reviewed


def _summary_from_assets(assets: list[dict[str, Any]]) -> NodeQualitySummary:
    statuses = [str(asset.get("quality_status") or "unchecked") for asset in assets]
    if any(status == "failed" for status in statuses):
        status = "failed"
    elif any(status == "warning" for status in statuses):
        status = "warning"
    elif statuses and all(status == "unavailable" for status in statuses):
        status = "unavailable"
    elif statuses and all(status == "passed" for status in statuses):
        status = "passed"
    else:
        status = "unchecked"
    issues = [
        QualityIssue.model_validate(issue)
        for asset in assets
        for issue in asset.get("quality_issues", [])
        if isinstance(issue, dict)
    ]
    score = (
        round(
            sum(float(asset.get("quality_score") or 0.0) for asset in assets) / len(assets),
            3,
        )
        if assets
        else _score_for_status(status)
    )
    return NodeQualitySummary(
        status=status,  # type: ignore[arg-type]
        score=score,
        reviewed_assets=len(assets),
        passed_assets=statuses.count("passed"),
        warning_assets=statuses.count("warning"),
        failed_assets=statuses.count("failed"),
        unavailable_assets=statuses.count("unavailable"),
        reviewer=REVIEWER_RULE_BASED,
        issues=issues,
    )


def _summary_from_status(
    status: str,
    *,
    reviewer: str,
    issues: list[QualityIssue] | None = None,
) -> NodeQualitySummary:
    return NodeQualitySummary(
        status=status,  # type: ignore[arg-type]
        score=_score_for_status(status),
        reviewed_assets=0,
        passed_assets=0,
        warning_assets=0,
        failed_assets=0,
        unavailable_assets=0,
        reviewer=reviewer,
        issues=issues or [],
    )


def _status_from_issues(issues: list[QualityIssue]) -> str:
    if any(issue.severity == "error" for issue in issues):
        return "failed"
    if any(issue.severity == "warning" for issue in issues):
        return "warning"
    return "passed"


def _score_for_status(status: str) -> float:
    return {
        "passed": 1.0,
        "warning": 0.7,
        "failed": 0.2,
        "unavailable": 0.0,
        "unchecked": 0.0,
    }.get(status, 0.0)


def _issue(
    code: str,
    severity: str,
    message: str,
    asset_id: str | None = None,
    *,
    details: dict[str, Any] | None = None,
) -> QualityIssue:
    return QualityIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        asset_id=asset_id,
        details=details or {},
    )


def _sync_quality_assets(
    output: dict[str, Any], reviewed_assets: list[dict[str, Any]]
) -> dict[str, Any]:
    synced = dict(output)
    if "assets" in synced or reviewed_assets:
        synced["assets"] = _replace_asset_list(synced.get("assets"), reviewed_assets)
    if "output_assets" in synced or reviewed_assets:
        synced["output_assets"] = _replace_asset_list(synced.get("output_assets"), reviewed_assets)
    for key in STRUCTURED_OUTPUT_ASSET_CONTAINER_KEYS:
        if isinstance(synced.get(key), list):
            synced[key] = _replace_asset_list(synced.get(key), reviewed_assets)
        elif isinstance(synced.get(key), dict):
            synced[key] = _replace_single_asset(synced[key], reviewed_assets)
    final_video = synced.get("final_video")
    if isinstance(final_video, dict):
        synced["final_video"] = _replace_single_asset(final_video, reviewed_assets)
    return synced


def _replace_asset_list(value: Any, reviewed_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    original = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    if not original:
        return [dict(asset) for asset in reviewed_assets]
    return [_replace_single_asset(asset, reviewed_assets) for asset in original]


def _replace_single_asset(
    asset: dict[str, Any], reviewed_assets: list[dict[str, Any]]
) -> dict[str, Any]:
    key = _asset_key(asset)
    for reviewed in reviewed_assets:
        if key and key == _asset_key(reviewed):
            return dict(reviewed)
    return dict(asset)


def _asset_key(asset: dict[str, Any]) -> str:
    for key in ("asset_id", "local_path", "public_url", "remote_url", "url", "metadata_path"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value}"
    return ""


def _asset_id(asset: dict[str, Any]) -> str | None:
    value = asset.get("asset_id")
    return str(value) if value not in (None, "") else None


def _asset_type(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_type") or asset.get("type") or asset.get("media_type") or "")


def _asset_failed(asset: dict[str, Any]) -> bool:
    status = str(asset.get("status") or "").lower()
    download_status = str(asset.get("download_status") or "").lower()
    return status == "failed" or download_status == "failed"


def _semantic_type_required(node_type: str) -> bool:
    return node_type in {"character-generation", "scene-generation", "storyboard"}


def _entity_id_required(node_type: str, asset: dict[str, Any]) -> bool:
    if node_type == "character-generation":
        return not (
            asset.get("entity_id")
            or asset.get("character_id")
            or asset.get("character_name")
            or asset.get("role")
        )
    if node_type == "scene-generation":
        return not (asset.get("entity_id") or asset.get("scene_id"))
    if node_type == "storyboard":
        return not (asset.get("entity_id") or asset.get("shot_id") or asset.get("scene_id"))
    return False


def _expected_asset_type(node_type: str) -> str:
    if node_type in {"character-generation", "scene-generation", "storyboard"}:
        return "image"
    if node_type == "storyboard-video-generation":
        return "video"
    return ""


def _has_preview_source(asset: dict[str, Any]) -> bool:
    return any(
        isinstance(asset.get(key), str) and str(asset.get(key)).strip()
        for key in ("local_path", "public_url", "remote_url", "url", "metadata_path")
    )


def _segment_is_ready(asset: dict[str, Any]) -> bool:
    status = str(asset.get("status") or "").lower()
    download_status = str(asset.get("download_status") or "").lower()
    return (
        download_status in {"downloaded", "ready"}
        or status in {"ready", "downloaded", "succeeded", "completed"}
    ) and _has_preview_source(asset)


def _assets_from_output(output: dict[str, Any]) -> list[dict[str, Any]]:
    return canonical_output_assets(output)


def _expected_scene_count(output: dict[str, Any], input_context: dict[str, Any]) -> int:
    return max(_storyboard_scene_count(output, input_context), _script_beat_count(input_context), 1)


def _storyboard_scene_count(output: dict[str, Any], input_context: dict[str, Any]) -> int:
    for payload in (output, input_context):
        structured = payload.get("structured_output") if isinstance(payload, dict) else None
        if isinstance(structured, dict):
            for key in ("storyboardItems", "scenes", "videoSegments"):
                value = structured.get(key)
                if isinstance(value, list):
                    return len(value)
        for key in ("storyboard", "storyboard_video"):
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, dict):
                scenes = value.get("scenes") or value.get("segments")
                if isinstance(scenes, list):
                    return len(scenes)
        scenes = payload.get("scenes") if isinstance(payload, dict) else None
        if isinstance(scenes, list):
            return len(scenes)
    return 0


def _script_beat_count(input_context: dict[str, Any]) -> int:
    script = input_context.get("script")
    if not isinstance(script, dict):
        return 0
    for key in ("shot_beats", "beats", "script_beats", "subtitle_lines"):
        value = script.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
