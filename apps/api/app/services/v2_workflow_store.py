import json
from pathlib import Path

from app.schemas.workflow_v2 import WorkflowV2
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_workflow_lock import v2_workflow_lock


def workflow_v2_path(data_dir: Path, workflow_id: str) -> Path:
    return validate_v2_data_path(
        data_dir,
        data_dir / "v2" / "workflows" / workflow_id / "workflow.json",
        operation="v2-workflow-path",
    )


def workflow_v2_runtime_dir(data_dir: Path, workflow_id: str) -> Path:
    return validate_v2_data_path(
        data_dir,
        data_dir / "v2" / "runs" / workflow_id,
        operation="v2-runtime-dir",
    )


class V2WorkflowStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def load_workflow(self, workflow_id: str) -> WorkflowV2:
        from app.services.workflow_v2 import WorkflowV2Error

        path = workflow_v2_path(self._data_dir, workflow_id)
        if not path.exists():
            raise WorkflowV2Error("workflow_not_found")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("workflow_schema_version") != 2:
            raise WorkflowV2Error("unsupported_workflow_schema_version")
        return _normalize_shot_primary_scenes(WorkflowV2.model_validate(payload))

    def save_workflow(self, workflow: WorkflowV2) -> WorkflowV2:
        with v2_workflow_lock(self._data_dir, workflow.workflow_id):
            path = workflow_v2_path(self._data_dir, workflow.workflow_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            workflow_v2_runtime_dir(self._data_dir, workflow.workflow_id).mkdir(
                parents=True,
                exist_ok=True,
            )
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(workflow.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(path)
            return workflow


def _normalize_shot_primary_scenes(workflow: WorkflowV2) -> WorkflowV2:
    script_plan = workflow.metadata.get("script_plan")
    if not isinstance(script_plan, dict):
        return workflow
    raw_shots = script_plan.get("shots")
    if not isinstance(raw_shots, list):
        return workflow
    screenplay_scene_by_shot_id = {
        str(raw_shot.get("shot_id")): str(raw_shot.get("scene_id"))
        for raw_shot in raw_shots
        if isinstance(raw_shot, dict)
        and str(raw_shot.get("shot_id") or "").strip()
        and str(raw_shot.get("scene_id") or "").strip()
    }
    active_scene_ids = {
        item.item_id
        for node in workflow.nodes
        for item in node.items
        if item.lifecycle_state == "active"
        and item.item_type == "scene"
        and item.node_id == "scene-generation"
    }
    for node in workflow.nodes:
        if node.node_id != "storyboard":
            continue
        for shot in node.items:
            if shot.lifecycle_state != "active" or shot.item_type != "shot":
                continue
            if shot.primary_scene_item_id:
                continue
            scene_id = screenplay_scene_by_shot_id.get(shot.shot_id or shot.item_id)
            if scene_id in active_scene_ids:
                shot.primary_scene_item_id = scene_id
    return workflow
