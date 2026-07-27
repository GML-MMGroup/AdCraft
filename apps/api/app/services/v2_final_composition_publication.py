from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Any, Callable

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    WorkflowAssetRelationTypeV2,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_provider_results import (
    V2ProviderExecutionContext,
    V2ProviderResultManifest,
)
from app.services.agent_trace import utc_now
from app.services.media_paths import public_url_for_path
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_final_composition_renderer import V2MediaProbe, V2MediaProbeResult
from app.services.v2_provider_result_store import (
    V2ProviderResultStore,
    V2ProviderResultStoreError,
)

MediaValidator = Callable[[Path], bool]


class V2FinalCompositionPublicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class V2FinalCompositionPublicationService:
    """Own deterministic Final Composition media and asset-version publication."""

    def __init__(
        self,
        settings: Settings,
        *,
        asset_store: V2AssetStoreService | None = None,
        media_validator: MediaValidator | None = None,
    ) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._asset_store = asset_store or V2AssetStoreService(self._data_dir)
        self._media_validator = media_validator or self._default_media_validator
        self._provider_results = V2ProviderResultStore(self._data_dir)

    @staticmethod
    def asset_id(workflow_id: str, slot_id: str) -> str:
        digest = sha256(f"{workflow_id}:{slot_id}".encode("utf-8")).hexdigest()[:24]
        return f"asset_final_{digest}"

    @staticmethod
    def version_id(composition_fingerprint: str) -> str:
        digest = composition_fingerprint.removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise V2FinalCompositionPublicationError(
                "v2_final_composition_publish_failed",
                "Final composition fingerprint is invalid.",
            )
        return f"ver_comp_{digest[:32]}"

    def find_reusable(
        self,
        *,
        workflow_id: str,
        slot_id: str,
        composition_fingerprint: str,
    ) -> WorkflowAssetVersionV2 | None:
        for record in self._asset_store.list_asset_versions_for_slot(
            workflow_id=workflow_id,
            slot_id=slot_id,
        ):
            if record.metadata.get("composition_fingerprint") != composition_fingerprint:
                continue
            reason = self._unavailable_reason(record)
            if reason is None:
                return record
            self._asset_store.mark_asset_version_unavailable(
                asset_id=record.asset_id,
                version_id=record.version_id,
                reason=reason,
            )
        return None

    def reconcile_pending(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> list[WorkflowAssetVersionV2]:
        recovered: list[WorkflowAssetVersionV2] = []
        for manifest in self._provider_results.list_manifests(workflow_id=workflow.workflow_id):
            if (
                manifest.slot_id != slot.slot_id
                or manifest.commit_status != "pending"
                or manifest.provider_status != "succeeded"
            ):
                continue
            fingerprint = manifest.provider_payload_snapshot.get("composition_fingerprint")
            fingerprint_payload = manifest.provider_payload_snapshot.get(
                "composition_fingerprint_payload"
            )
            if not isinstance(fingerprint, str) or not isinstance(
                fingerprint_payload,
                dict,
            ):
                self._provider_results.mark_rejected(
                    manifest,
                    code="v2_final_composition_manifest_identity_missing",
                    message="Pending Final Composition manifest lacks canonical identity.",
                )
                continue
            output = next(
                (candidate for candidate in manifest.outputs if candidate.is_primary),
                None,
            )
            if output is None:
                self._provider_results.mark_rejected(
                    manifest,
                    code="v2_final_composition_manifest_output_missing",
                    message="Pending Final Composition manifest lacks a primary output.",
                )
                continue
            try:
                record = self.publish(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                    source_path=self._data_dir / output.staging_path,
                    composition_fingerprint=fingerprint,
                    fingerprint_payload=fingerprint_payload,
                    fingerprint_contract_version=str(
                        manifest.provider_payload_snapshot.get("fingerprint_contract_version")
                        or "v2-final-composition-fingerprint-v1"
                    ),
                    source_action=manifest.source_action,
                    select_result=manifest.select_generated,
                    source_render_id=manifest.attempt_id,
                    provider_payload=manifest.provider_payload_snapshot,
                    result_metadata=manifest.provider_result_metadata,
                    reference_asset_ids=manifest.reference_asset_ids,
                )
            except (OSError, V2FinalCompositionPublicationError) as exc:
                self._provider_results.mark_rejected(
                    manifest,
                    code="v2_final_composition_manifest_recovery_failed",
                    message=str(exc)[:500],
                )
                continue
            recovered.append(record)
        return recovered

    def publish(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        source_path: Path,
        composition_fingerprint: str,
        fingerprint_payload: dict[str, Any],
        fingerprint_contract_version: str,
        source_action: str,
        select_result: bool,
        source_render_id: str | None,
        provider_payload: dict[str, Any],
        result_metadata: dict[str, Any],
        reference_asset_ids: list[str],
    ) -> WorkflowAssetVersionV2:
        asset_id = self._publication_asset_id(workflow, slot)
        version_id = self.version_id(composition_fingerprint)
        existing = self._asset_store.load_asset_version(asset_id, version_id)
        if existing is not None:
            if existing.metadata.get("composition_fingerprint") != composition_fingerprint:
                raise V2FinalCompositionPublicationError(
                    "v2_final_composition_publish_failed",
                    "Deterministic final version identity conflicts with stored metadata.",
                )
            if self._unavailable_reason(existing) is None:
                return existing
        source_path = validate_v2_data_path(
            self._data_dir,
            source_path,
            operation="v2-final-composition-publish-source",
        )
        if not self._media_validator(source_path):
            raise V2FinalCompositionPublicationError(
                "v2_final_composition_publish_failed",
                "Final composition output did not pass media validation.",
            )
        manifest_identity: dict[str, str] = {}
        publish_source = source_path
        if source_action == "editor_export" and source_render_id:
            try:
                manifest = self._ensure_editor_manifest(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                    source_path=source_path,
                    composition_fingerprint=composition_fingerprint,
                    source_render_id=source_render_id,
                    source_action=source_action,
                    select_result=select_result,
                    provider_payload=provider_payload,
                    result_metadata=result_metadata,
                    reference_asset_ids=reference_asset_ids,
                )
            except V2ProviderResultStoreError as exc:
                if self._settings.media_mode.strip().lower() != "mock":
                    raise V2FinalCompositionPublicationError(exc.code, str(exc)) from exc
            else:
                publish_source = self._data_dir / manifest.outputs[0].staging_path
                manifest_identity = {
                    "execution_id": manifest.execution_id,
                    "attempt_id": manifest.attempt_id,
                }
        extension = ".mp4"
        relative_path = (
            Path("assets")
            / "generated"
            / workflow.workflow_id
            / "final-composition"
            / asset_id
            / f"{version_id}{extension}"
        )
        target = validate_v2_data_path(
            self._data_dir,
            self._data_dir / relative_path,
            operation="v2-final-composition-publish-target",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        shutil.copyfile(publish_source, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        accepted_timeline = provider_payload.get("accepted_timeline")
        timeline_identity = accepted_timeline if isinstance(accepted_timeline, dict) else {}
        metadata = {
            **result_metadata,
            "timeline_id": timeline_identity.get("timeline_id"),
            "timeline_version": timeline_identity.get("timeline_version"),
            "composition_fingerprint": composition_fingerprint,
            "fingerprint_contract_version": fingerprint_contract_version,
            "composition_fingerprint_payload": fingerprint_payload,
            "renderer_contract": fingerprint_payload.get("renderer", {}),
            "toolchain_fingerprint": fingerprint_payload.get("renderer", {}).get(
                "toolchain_fingerprint"
            ),
            "source_asset_versions": _source_lineage(fingerprint_payload),
            "source_render_id": source_render_id,
            "source_action": source_action,
            "select_result": select_result,
            "availability_status": "ready",
            "publication_manifest": manifest_identity,
        }
        return self._asset_store.save_asset_version(
            WorkflowAssetVersionV2(
                asset_id=asset_id,
                version_id=version_id,
                media_type="video",
                source_type=("derived" if source_action == "editor_export" else "generated"),
                file_path=relative_path.as_posix(),
                public_url=public_url_for_path(relative_path.as_posix()),
                workflow_id=workflow.workflow_id,
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                semantic_type="final_video",
                provider_payload_snapshot=provider_payload,
                reference_asset_ids=reference_asset_ids,
                created_at=utc_now().isoformat(),
                created_by="v2-final-composition-publication",
                metadata=metadata,
            )
        )

    def _publication_asset_id(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
    ) -> str:
        if slot.selected_asset_id and slot.selected_version_id:
            selected = self._asset_store.load_asset_version(
                slot.selected_asset_id,
                slot.selected_version_id,
            )
            if (
                selected is not None
                and selected.workflow_id == workflow.workflow_id
                and selected.slot_id == slot.slot_id
                and selected.media_type == "video"
                and selected.semantic_type == "final_video"
            ):
                return selected.asset_id
        return self.asset_id(workflow.workflow_id, slot.slot_id)

    def apply_relations(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2,
        source_action: str,
        select_result: bool,
    ) -> None:
        previous_asset_id = slot.selected_asset_id
        previous_version_id = slot.selected_version_id
        if (
            select_result
            and previous_asset_id
            and previous_version_id
            and previous_version_id != record.version_id
        ):
            slot.history_version_ids = list(
                dict.fromkeys([*slot.history_version_ids, previous_version_id])
            )
            self._asset_store.create_relation(
                relation_type="history_version_for_slot",
                source_asset_id=previous_asset_id,
                target_workflow_id=workflow.workflow_id,
                target_node_id=slot.node_id,
                target_item_id=item.item_id,
                target_slot_id=slot.slot_id,
                metadata={"version_id": previous_version_id, "source_action": source_action},
            )
        self._replace_relation(
            workflow=workflow,
            item=item,
            slot=slot,
            record=record,
            relation_type="working_version_for_slot",
            source_action=source_action,
        )
        slot.current_working_asset_id = record.asset_id
        slot.current_working_version_id = record.version_id
        if select_result:
            self._replace_relation(
                workflow=workflow,
                item=item,
                slot=slot,
                record=record,
                relation_type="selected_for_slot",
                source_action=source_action,
            )
            slot.selected_asset_id = record.asset_id
            slot.selected_version_id = record.version_id
            slot.status = "completed"
        self._mark_editor_manifest_committed(record)

    def _replace_relation(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2,
        relation_type: WorkflowAssetRelationTypeV2,
        source_action: str,
    ) -> None:
        current = self._asset_store.list_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type=relation_type,
        )
        matching = next(
            (
                relation
                for relation in current
                if relation.source_asset_id == record.asset_id
                and relation.metadata.get("version_id") == record.version_id
            ),
            None,
        )
        if matching is not None:
            return
        self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type=relation_type,
        )
        self._asset_store.create_relation(
            relation_type=relation_type,
            source_asset_id=record.asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=item.item_id,
            target_slot_id=slot.slot_id,
            metadata={"version_id": record.version_id, "source_action": source_action},
        )

    def _unavailable_reason(self, record: WorkflowAssetVersionV2) -> str | None:
        path = validate_v2_data_path(
            self._data_dir,
            record.file_path,
            operation="v2-final-composition-reuse",
        )
        if not path.is_file():
            return "final_media_missing"
        if path.stat().st_size <= 0:
            return "final_media_empty"
        if record.media_type != "video":
            return "final_media_type_invalid"
        if not self._media_validator(path):
            return "final_media_probe_failed"
        return None

    def _ensure_editor_manifest(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        source_path: Path,
        composition_fingerprint: str,
        source_render_id: str,
        source_action: str,
        select_result: bool,
        provider_payload: dict[str, Any],
        result_metadata: dict[str, Any],
        reference_asset_ids: list[str],
    ) -> V2ProviderResultManifest:
        execution_id = f"final_{composition_fingerprint.removeprefix('sha256:')[:24]}"
        context = V2ProviderExecutionContext(
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            attempt_id=source_render_id,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            media_type="video",
            input_fingerprint=composition_fingerprint,
            source_action=source_action,
            select_generated=select_result,
        )
        existing = self._provider_results.load_manifest(
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            slot_id=slot.slot_id,
            attempt_id=source_render_id,
        )
        if existing is not None:
            return existing
        staging_path = self._provider_results.stage_provider_output(
            context=context,
            asset_bytes=source_path.read_bytes(),
            local_file_path=None,
        )
        return self._provider_results.persist_immediate_result(
            context=context,
            provider_name="local_composition_ffmpeg",
            provider_model=str(result_metadata.get("provider_model") or "ffmpeg"),
            staging_path=staging_path,
            generation_plan_snapshot={
                "composition_fingerprint": composition_fingerprint,
                "source_render_id": source_render_id,
            },
            provider_payload_snapshot=provider_payload,
            provider_result_metadata=result_metadata,
            reference_asset_ids=reference_asset_ids,
        )

    def _mark_editor_manifest_committed(self, record: WorkflowAssetVersionV2) -> None:
        identity = record.metadata.get("publication_manifest")
        if not isinstance(identity, dict):
            return
        execution_id = identity.get("execution_id")
        attempt_id = identity.get("attempt_id")
        if not isinstance(execution_id, str) or not isinstance(attempt_id, str):
            return
        manifest = self._provider_results.load_manifest(
            workflow_id=str(record.workflow_id),
            execution_id=execution_id,
            slot_id=str(record.slot_id),
            attempt_id=attempt_id,
        )
        if manifest is None or manifest.commit_status == "committed":
            return
        self._provider_results.mark_committed(
            manifest,
            canonical_asset_ids=[record.asset_id],
            canonical_version_ids=[record.version_id],
        )

    def _default_media_validator(self, path: Path) -> bool:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        if self._settings.media_mode.strip().lower() == "mock":
            return True
        probe: V2MediaProbeResult = V2MediaProbe(ffprobe_path=self._settings.ffprobe_path)(path)
        return probe.error is None and bool(probe.video_codec)


def _source_lineage(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [
        *payload.get("visual_sources", []),
        *payload.get("audio_sources", []),
    ]
    return [
        {key: source.get(key) for key in ("asset_id", "version_id", "content_sha256")}
        for source in sources
        if isinstance(source, dict)
    ]
