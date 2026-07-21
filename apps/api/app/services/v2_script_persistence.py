from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import threading
from typing import Any
from pydantic import ValidationError

from app.schemas.workflow_v2_planning import V2ScriptPlan
from app.schemas.workflow_v2_screenplay import (
    V2ScriptPendingTransaction,
    V2ScriptPlanV2,
    V2ScriptShotV2,
    V2ScriptVersionIndex,
    V2ScriptVersionRecord,
    V2ScriptVersionSummary,
)
from app.schemas.workflow_v2 import WorkflowV2
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_event_store import V2EventStore
from app.services.v2_screenplay_renderer import V2ScreenplayRenderer
from app.services.v2_workflow_lock import v2_workflow_lock
from app.services.v2_workflow_store import workflow_v2_path


class V2ScriptPersistenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class V2ScriptPersistenceAdapter:
    def __init__(self) -> None:
        self._renderer = V2ScreenplayRenderer()

    def normalize_metadata_plan(
        self,
        payload: Any,
    ) -> tuple[V2ScriptPlanV2, str | None]:
        if not isinstance(payload, dict):
            raise V2ScriptPersistenceError(
                "script_plan_unavailable",
                "The workflow does not contain a recoverable screenplay.",
            )
        version = payload.get("script_plan_version", 1)
        try:
            if version == 2:
                normalized = deepcopy(payload)
                normalized["shots"] = [
                    {
                        key: value
                        for key, value in shot.items()
                        if key in V2ScriptShotV2.model_fields
                    }
                    for shot in normalized.get("shots", [])
                    if isinstance(shot, dict)
                ]
                plan = V2ScriptPlanV2.model_validate(normalized)
                return self._render(plan), None
            if version != 1:
                raise ValueError(f"unsupported script plan version: {version}")
            legacy = V2ScriptPlan.model_validate(payload)
            shots = [
                V2ScriptShotV2(
                    shot_id=shot.shot_id,
                    scene_id=shot.scene_id,
                    shot_index=index,
                    product_ids=shot.product_ids,
                    character_ids=shot.character_ids,
                    scene_ids=shot.scene_ids,
                    reference_item_ids=list(
                        dict.fromkeys([*shot.product_ids, *shot.character_ids, *shot.scene_ids])
                    ),
                    description=shot.description,
                    dialogue=[],
                    narration=shot.narration,
                    visual_prompt=shot.visual_prompt,
                    duration_seconds=shot.duration_seconds,
                )
                for index, shot in enumerate(legacy.shots, start=1)
            ]
            scenes = [
                scene.model_copy(
                    update={
                        "shot_ids": [
                            shot.shot_id for shot in shots if shot.scene_id == scene.scene_id
                        ],
                        "duration_seconds": sum(
                            shot.duration_seconds
                            for shot in shots
                            if shot.scene_id == scene.scene_id
                        ),
                    },
                    deep=True,
                )
                for scene in legacy.scenes
            ]
            plan = V2ScriptPlanV2(
                **legacy.model_dump(
                    mode="python",
                    exclude={
                        "script_plan_version",
                        "script_text",
                        "scenes",
                        "shots",
                        "duration_seconds",
                    },
                ),
                script_plan_version=2,
                script_text="",
                scenes=scenes,
                shots=shots,
                duration_seconds=sum(shot.duration_seconds for shot in shots),
            )
            return self._render(plan), "metadata.script_plan.v1"
        except (ValidationError, ValueError) as exc:
            raise V2ScriptPersistenceError(
                "script_plan_unavailable",
                "The workflow screenplay cannot be normalized to version 2.",
            ) from exc

    def validate_record(self, payload: Any) -> V2ScriptVersionRecord:
        try:
            record = V2ScriptVersionRecord.model_validate(payload)
            self._renderer.validate_canonical_text(record.script)
            if record.script.script_version_id != record.script_version_id:
                raise ValueError("script version identifiers do not match")
            if screenplay_content_hash(record.script) != record.content_hash:
                raise ValueError("script version content hash does not match")
            return record
        except Exception as exc:
            raise V2ScriptPersistenceError(
                "script_version_corrupt",
                "The persisted screenplay version is corrupt.",
            ) from exc

    def _render(self, plan: V2ScriptPlanV2) -> V2ScriptPlanV2:
        return plan.model_copy(
            update={"script_text": self._renderer.render(plan)},
            deep=True,
        )


class V2ScriptVersionStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._adapter = V2ScriptPersistenceAdapter()

    def root(self, workflow_id: str) -> Path:
        return validate_v2_data_path(
            self._data_dir,
            self._data_dir / "v2" / "workflows" / workflow_id / "script_versions",
            operation="v2-script-version-root",
        )

    def version_path(self, workflow_id: str, script_version_id: str) -> Path:
        _validate_path_id(script_version_id, "script_version_id")
        return validate_v2_data_path(
            self._data_dir,
            self.root(workflow_id) / f"{script_version_id}.json",
            operation="v2-script-version-path",
        )

    def index_path(self, workflow_id: str) -> Path:
        return self.root(workflow_id) / "index.json"

    def pending_path(self, workflow_id: str) -> Path:
        return self.root(workflow_id) / "pending-transaction.json"

    def load_version(self, workflow_id: str, script_version_id: str) -> V2ScriptVersionRecord:
        path = self.version_path(workflow_id, script_version_id)
        if not path.is_file():
            raise V2ScriptPersistenceError(
                "script_version_not_found",
                "The requested screenplay version does not exist.",
            )
        try:
            return self._adapter.validate_record(json.loads(path.read_text(encoding="utf-8")))
        except V2ScriptPersistenceError:
            raise
        except Exception as exc:
            raise V2ScriptPersistenceError(
                "script_version_corrupt",
                "The persisted screenplay version is corrupt.",
            ) from exc

    def load_index(self, workflow_id: str) -> V2ScriptVersionIndex | None:
        path = self.index_path(workflow_id)
        if not path.is_file():
            return None
        try:
            return V2ScriptVersionIndex.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise V2ScriptPersistenceError(
                "script_version_corrupt",
                "The screenplay version index is corrupt.",
            ) from exc

    def write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def workflow_lock(self, workflow_id: str) -> AbstractContextManager[None]:
        return v2_workflow_lock(self._data_dir, workflow_id)


class V2ScriptTransactionStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._versions = V2ScriptVersionStore(data_dir)
        self._events = V2EventStore(data_dir)

    def commit(
        self,
        *,
        workflow: WorkflowV2,
        record: V2ScriptVersionRecord | None,
        index: V2ScriptVersionIndex,
        pending: V2ScriptPendingTransaction,
    ) -> int:
        workflow_id = workflow.workflow_id
        root = self._versions.root(workflow_id)
        root.mkdir(parents=True, exist_ok=True)
        workflow_payload = workflow.model_dump(mode="json")
        index_payload = index.model_dump(mode="json")
        pending_payload = pending.model_dump(mode="json")
        record_payload = record.model_dump(mode="json") if record is not None else None
        WorkflowV2.model_validate(workflow_payload)
        V2ScriptVersionIndex.model_validate(index_payload)
        V2ScriptPendingTransaction.model_validate(pending_payload)
        if record_payload is not None:
            self._versions._adapter.validate_record(record_payload)

        prior_index = self._versions.load_index(workflow_id)
        target_path = self._versions.version_path(workflow_id, pending.target_script_version_id)
        workflow_path = workflow_v2_path(self._data_dir, workflow_id)
        committed = False
        created_target = False
        try:
            if record_payload is not None:
                if target_path.exists():
                    raise V2ScriptPersistenceError(
                        "script_persistence_failed",
                        "The target screenplay version already exists.",
                    )
                self._versions.write_json(target_path, record_payload)
                created_target = True
            else:
                self._versions.load_version(workflow_id, pending.target_script_version_id)
            self._versions.write_json(self._versions.pending_path(workflow_id), pending_payload)
            self._versions.write_json(self._versions.index_path(workflow_id), index_payload)
            self._versions.write_json(workflow_path, workflow_payload)
            committed = True
            self._append_event_intents(workflow_id, pending)
            self._versions.pending_path(workflow_id).unlink(missing_ok=True)
            return self._events.events_cursor(workflow_id)
        except Exception as exc:
            if not committed:
                if prior_index is None:
                    self._versions.index_path(workflow_id).unlink(missing_ok=True)
                else:
                    self._versions.write_json(
                        self._versions.index_path(workflow_id),
                        prior_index.model_dump(mode="json"),
                    )
                if created_target:
                    target_path.unlink(missing_ok=True)
                self._versions.pending_path(workflow_id).unlink(missing_ok=True)
            if isinstance(exc, V2ScriptPersistenceError):
                raise
            raise V2ScriptPersistenceError(
                "script_persistence_failed",
                "The screenplay transaction could not be persisted.",
            ) from exc

    def recover(self, workflow_id: str, workflow: WorkflowV2) -> WorkflowV2:
        pending_path = self._versions.pending_path(workflow_id)
        if not pending_path.is_file():
            return workflow
        try:
            pending = V2ScriptPendingTransaction.model_validate_json(
                pending_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise V2ScriptPersistenceError(
                "script_version_corrupt",
                "The pending screenplay transaction is corrupt.",
            ) from exc
        selected_id = str(workflow.metadata.get("selected_script_version_id") or "")
        index = self._versions.load_index(workflow_id)
        if selected_id == pending.target_script_version_id:
            record = self._versions.load_version(workflow_id, pending.target_script_version_id)
            summary = script_version_summary(record)
            summaries = list(index.versions if index else [])
            if not any(item.script_version_id == summary.script_version_id for item in summaries):
                summaries.insert(0, summary)
            recovered_index = V2ScriptVersionIndex(
                selected_script_version_id=selected_id,
                versions=summaries,
            )
            self._versions.write_json(
                self._versions.index_path(workflow_id),
                recovered_index.model_dump(mode="json"),
            )
            self._append_event_intents(workflow_id, pending)
        else:
            target_path = self._versions.version_path(
                workflow_id,
                pending.target_script_version_id,
            )
            target_path.unlink(missing_ok=True)
            if index is not None:
                recovered_index = index.model_copy(
                    update={
                        "selected_script_version_id": selected_id
                        or pending.prior_selected_script_version_id,
                        "versions": [
                            item
                            for item in index.versions
                            if item.script_version_id != pending.target_script_version_id
                        ],
                    },
                    deep=True,
                )
                self._versions.write_json(
                    self._versions.index_path(workflow_id),
                    recovered_index.model_dump(mode="json"),
                )
        pending_path.unlink(missing_ok=True)
        return workflow

    def _append_event_intents(
        self,
        workflow_id: str,
        pending: V2ScriptPendingTransaction,
    ) -> None:
        existing = self._events.load_events(workflow_id)
        existing_keys = {
            (event.event_type, str(event.payload.get("transaction_id") or "")) for event in existing
        }
        for intent in pending.event_intents:
            key = (intent.event_type, pending.transaction_id)
            if key in existing_keys:
                continue
            self._events.append_event(
                workflow_id,
                intent.event_type,
                node_id=intent.node_id,
                item_id=intent.item_id,
                slot_id=intent.slot_id,
                payload={**intent.payload, "transaction_id": pending.transaction_id},
            )
            existing_keys.add(key)


def script_version_summary(record: V2ScriptVersionRecord) -> V2ScriptVersionSummary:
    return V2ScriptVersionSummary(
        script_version_id=record.script_version_id,
        parent_script_version_id=record.parent_script_version_id,
        created_at=record.created_at,
        source_action=record.source_action,
        script_title=record.script.script_title,
        content_hash=record.content_hash,
        structural_diff_summary=record.structural_diff.model_dump(mode="json"),
    )


def screenplay_content_hash(plan: V2ScriptPlanV2) -> str:
    payload = plan.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def _validate_path_id(value: str, label: str) -> None:
    if not value or Path(value).name != value or "/" in value or "\\" in value:
        raise V2ScriptPersistenceError("invalid_script_document", f"Invalid {label}.")
