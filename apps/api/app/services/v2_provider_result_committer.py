from __future__ import annotations

import hashlib
from pathlib import Path

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_provider_results import V2ProviderResultManifest
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_data_path
from app.services.v2_media_quality_gate import detect_media_format
from app.services.v2_provider_result_store import V2ProviderResultStore


class V2ProviderResultCommitError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class V2ProviderResultCommitter:
    """Coordinator-side validation and finalization for durable provider results."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._store = V2ProviderResultStore(data_dir)

    def validate_manifest(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        manifest: V2ProviderResultManifest,
        expected_input_fingerprint: str,
    ) -> Path:
        if (
            manifest.workflow_id != workflow.workflow_id
            or manifest.node_id != slot.node_id
            or manifest.item_id != item.item_id
            or manifest.slot_id != slot.slot_id
        ):
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result manifest does not belong to the current slot.",
            )
        if manifest.input_fingerprint != expected_input_fingerprint:
            raise V2ProviderResultCommitError(
                "v2_provider_result_input_mismatch",
                "Provider result input no longer matches the current slot state.",
            )
        if manifest.provider_status != "succeeded" or manifest.commit_status != "pending":
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result manifest is not pending successful output.",
            )
        primary_outputs = [output for output in manifest.outputs if output.is_primary]
        if len(primary_outputs) != 1:
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result manifest requires exactly one primary output.",
            )
        output = primary_outputs[0]
        if output.media_type != manifest.media_type or output.media_type != slot.media_type:
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result output media type does not match its slot.",
            )
        try:
            path = validate_v2_data_path(
                self._data_dir,
                output.staging_path,
                operation="v2-provider-result-commit-output",
            )
        except V2DataBoundaryError as exc:
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result output is outside V2 data storage.",
            ) from exc
        relative_parts = path.relative_to(self._data_dir.resolve()).parts
        if len(relative_parts) < 2 or relative_parts[:2] != ("assets", "generated-provider"):
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result output is not in the provider staging area.",
            )
        if not path.exists() or not path.is_file():
            raise V2ProviderResultCommitError(
                "v2_provider_result_output_missing",
                "Provider result output no longer exists.",
            )
        detected = detect_media_format(path)
        if (
            detected is None
            or detected.media_type != output.media_type
            or detected.mime_type != output.mime_type
        ):
            raise V2ProviderResultCommitError(
                "v2_provider_result_manifest_invalid",
                "Provider result output media descriptor could not be verified.",
            )
        if path.stat().st_size != output.byte_size:
            raise V2ProviderResultCommitError(
                "v2_provider_result_digest_mismatch",
                "Provider result output size changed before canonical commit.",
            )
        if _sha256_file(path) != output.sha256:
            raise V2ProviderResultCommitError(
                "v2_provider_result_digest_mismatch",
                "Provider result output digest changed before canonical commit.",
            )
        return path

    def mark_committed(
        self,
        manifest: V2ProviderResultManifest,
        *,
        asset_id: str,
        version_id: str,
    ) -> V2ProviderResultManifest:
        return self._store.mark_committed(
            manifest,
            canonical_asset_ids=[asset_id],
            canonical_version_ids=[version_id],
        )

    def reject(
        self,
        manifest: V2ProviderResultManifest,
        error: V2ProviderResultCommitError,
    ) -> V2ProviderResultManifest:
        return self._store.mark_rejected(
            manifest,
            code=error.code,
            message=str(error),
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
