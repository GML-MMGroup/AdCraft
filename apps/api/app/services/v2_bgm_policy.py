from __future__ import annotations

from typing import Any

from app.schemas.workflow_v2 import WorkflowV2


BGM_SOFT_SKIP_CODE = "v2_bgm_provider_unconfigured_soft_skip"


def workflow_requires_bgm(workflow: WorkflowV2) -> bool:
    if workflow.audio_mode == "none":
        return False
    metadata = workflow.metadata if isinstance(workflow.metadata, dict) else {}
    request_metadata = metadata.get("request") if isinstance(metadata.get("request"), dict) else {}
    if _truthy_any(metadata, ("bgm_required", "requires_bgm", "require_bgm", "audio_required")):
        return True
    if _truthy_any(
        request_metadata, ("bgm_required", "requires_bgm", "require_bgm", "audio_required")
    ):
        return True
    return False


def workflow_allows_muted_final(workflow: WorkflowV2) -> bool:
    return not workflow_requires_bgm(workflow)


def _truthy_any(values: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(bool(values.get(key)) for key in keys)
