from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from app.schemas.workflow_v2_provider_results import (
    V2ProviderExecutionContext,
    V2ProviderManifestError,
    V2ProviderOutputDescriptor,
    V2ProviderResultManifest,
)
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_data_path
from app.services.v2_media_quality_gate import detect_media_format, detect_media_format_from_bytes
from app.services.v2_workflow_store import workflow_v2_runtime_dir


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|token|secret|authorization|credential|password|signature|sig|expires|"
    r"access[_-]?key|session[_-]?token)",
    re.IGNORECASE,
)
_MEDIA_KEY = re.compile(r"(?:base64|bytes|binary|data_url|encoded)", re.IGNORECASE)


class V2ProviderResultStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def slot_key(slot_id: str) -> str:
    return hashlib.sha256(slot_id.encode("utf-8")).hexdigest()[:24]


def provider_result_id(
    context: V2ProviderExecutionContext,
    provider_name: str,
) -> str:
    payload = {
        "attempt_id": context.attempt_id,
        "execution_id": context.execution_id,
        "input_fingerprint": context.input_fingerprint,
        "provider_name": provider_name,
        "slot_id": context.slot_id,
        "workflow_id": context.workflow_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"presult_{hashlib.sha256(encoded).hexdigest()[:32]}"


class V2ProviderResultStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def persist_immediate_result(
        self,
        *,
        context: V2ProviderExecutionContext,
        provider_name: str,
        provider_model: str | None,
        staging_path: Path,
        generation_plan_snapshot: dict[str, Any],
        provider_payload_snapshot: dict[str, Any],
        provider_result_metadata: dict[str, Any],
        reference_asset_ids: list[str],
    ) -> V2ProviderResultManifest:
        self._validate_context(context)
        resolved_output = self._validated_staging_path(staging_path)
        if not resolved_output.exists() or not resolved_output.is_file():
            raise V2ProviderResultStoreError(
                "v2_provider_result_output_missing",
                "Provider result output does not exist.",
            )
        descriptor = self._output_descriptor(context, resolved_output, provider_result_metadata)
        now = datetime.now(timezone.utc)
        manifest = V2ProviderResultManifest(
            provider_result_id=provider_result_id(context, provider_name),
            workflow_id=context.workflow_id,
            execution_id=context.execution_id,
            attempt_id=context.attempt_id,
            node_id=context.node_id,
            item_id=context.item_id,
            slot_id=context.slot_id,
            slot_key=slot_key(context.slot_id),
            slot_type=context.slot_type,
            media_type=context.media_type,
            input_fingerprint=context.input_fingerprint,
            provider_name=provider_name,
            provider_model=provider_model,
            source_action=context.source_action,
            select_generated=context.select_generated,
            provider_status="succeeded",
            commit_status="pending",
            outputs=[descriptor],
            reference_asset_ids=[str(asset_id) for asset_id in reference_asset_ids],
            generation_plan_snapshot=_sanitize_snapshot(generation_plan_snapshot),
            provider_payload_snapshot=_sanitize_snapshot(provider_payload_snapshot),
            provider_result_metadata=_sanitize_snapshot(provider_result_metadata),
            created_at=now,
            updated_at=now,
        )
        self.create_manifest(manifest)
        return manifest

    def stage_provider_output(
        self,
        *,
        context: V2ProviderExecutionContext,
        asset_bytes: bytes | None,
        local_file_path: str | None,
    ) -> Path:
        """Atomically stage one immediate provider output without creating canonical metadata."""
        self._validate_context(context)
        if asset_bytes is None and not local_file_path:
            raise V2ProviderResultStoreError(
                "v2_provider_result_output_missing",
                "Provider result did not include bytes or a local output path.",
            )
        if asset_bytes is not None:
            detected = detect_media_format_from_bytes(asset_bytes)
            if detected is None or detected.media_type != context.media_type:
                raise V2ProviderResultStoreError(
                    "v2_provider_result_manifest_invalid",
                    "Provider output media type could not be verified.",
                )
            extension = detected.file_extension
            source_bytes = asset_bytes
        else:
            source_path = self._validated_provider_source_path(Path(str(local_file_path)))
            if not source_path.exists() or not source_path.is_file():
                raise V2ProviderResultStoreError(
                    "v2_provider_result_output_missing",
                    "Provider output file does not exist.",
                )
            detected = detect_media_format(source_path)
            if detected is None or detected.media_type != context.media_type:
                raise V2ProviderResultStoreError(
                    "v2_provider_result_manifest_invalid",
                    "Provider output media type could not be verified.",
                )
            extension = detected.file_extension
            source_bytes = source_path.read_bytes()
        output_path = validate_v2_data_path(
            self._data_dir,
            self._data_dir
            / "assets"
            / "generated-provider"
            / context.workflow_id
            / slot_key(context.slot_id)
            / context.attempt_id
            / f"output-0{extension}",
            operation="v2-provider-result-stage-output",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.tmp")
        temporary.write_bytes(source_bytes)
        temporary.replace(output_path)
        return output_path

    def create_manifest(self, manifest: V2ProviderResultManifest) -> V2ProviderResultManifest:
        self._validate_manifest(manifest)
        path = self.manifest_path(
            workflow_id=manifest.workflow_id,
            execution_id=manifest.execution_id,
            slot_id=manifest.slot_id,
            attempt_id=manifest.attempt_id,
        )
        if path.exists():
            return self._load_path(path)
        self._atomic_write(path, manifest)
        return manifest

    def load_manifest(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        slot_id: str,
        attempt_id: str,
    ) -> V2ProviderResultManifest | None:
        path = self.manifest_path(
            workflow_id=workflow_id,
            execution_id=execution_id,
            slot_id=slot_id,
            attempt_id=attempt_id,
        )
        return self._load_path(path) if path.exists() else None

    def list_manifests(
        self,
        *,
        workflow_id: str,
        execution_id: str | None = None,
    ) -> list[V2ProviderResultManifest]:
        self._validate_id("workflow_id", workflow_id)
        root = workflow_v2_runtime_dir(self._data_dir, workflow_id) / "provider-results"
        if execution_id is not None:
            self._validate_id("execution_id", execution_id)
            root = root / execution_id
        root = validate_v2_data_path(self._data_dir, root, operation="v2-provider-result-list")
        if not root.exists():
            return []
        manifests: list[V2ProviderResultManifest] = []
        pattern = "*/*.json" if execution_id is not None else "*/*/*.json"
        for path in sorted(root.glob(pattern)):
            manifest = self._load_path(path)
            if manifest.workflow_id == workflow_id and (
                execution_id is None or manifest.execution_id == execution_id
            ):
                manifests.append(manifest)
        return manifests

    def update_manifest(self, manifest: V2ProviderResultManifest) -> V2ProviderResultManifest:
        self._validate_manifest(manifest)
        updated = manifest.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        path = self.manifest_path(
            workflow_id=updated.workflow_id,
            execution_id=updated.execution_id,
            slot_id=updated.slot_id,
            attempt_id=updated.attempt_id,
        )
        self._atomic_write(path, updated)
        return updated

    def mark_committed(
        self,
        manifest: V2ProviderResultManifest,
        *,
        canonical_asset_ids: list[str],
        canonical_version_ids: list[str],
    ) -> V2ProviderResultManifest:
        return self.update_manifest(
            manifest.model_copy(
                update={
                    "commit_status": "committed",
                    "canonical_asset_ids": list(canonical_asset_ids),
                    "canonical_version_ids": list(canonical_version_ids),
                    "committed_at": datetime.now(timezone.utc),
                }
            )
        )

    def mark_rejected(
        self,
        manifest: V2ProviderResultManifest,
        *,
        code: str,
        message: str,
    ) -> V2ProviderResultManifest:
        return self.update_manifest(
            manifest.model_copy(
                update={
                    "commit_status": "rejected",
                    "error": V2ProviderManifestError(code=code, message=message),
                }
            )
        )

    def manifest_path(
        self,
        *,
        workflow_id: str,
        execution_id: str,
        slot_id: str,
        attempt_id: str,
    ) -> Path:
        self._validate_id("workflow_id", workflow_id)
        self._validate_id("execution_id", execution_id)
        self._validate_id("attempt_id", attempt_id)
        return validate_v2_data_path(
            self._data_dir,
            workflow_v2_runtime_dir(self._data_dir, workflow_id)
            / "provider-results"
            / execution_id
            / slot_key(slot_id)
            / f"{attempt_id}.json",
            operation="v2-provider-result-manifest-path",
        )

    def _validated_staging_path(self, staging_path: Path) -> Path:
        try:
            resolved = validate_v2_data_path(
                self._data_dir,
                staging_path,
                operation="v2-provider-result-staging-path",
            )
        except V2DataBoundaryError as exc:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result staging path is outside the V2 data boundary.",
            ) from exc
        if "generated-provider" not in resolved.relative_to(self._data_dir.resolve()).parts:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result staging path must be provider-generated media.",
            )
        return resolved

    def _validated_provider_source_path(self, source_path: Path) -> Path:
        try:
            resolved = validate_v2_data_path(
                self._data_dir,
                source_path,
                operation="v2-provider-result-source-path",
            )
        except V2DataBoundaryError as exc:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result output path is outside the V2 data boundary.",
            ) from exc
        if resolved.relative_to(self._data_dir.resolve()).parts[0] != "assets":
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result output path must be V2 asset storage.",
            )
        return resolved

    def _output_descriptor(
        self,
        context: V2ProviderExecutionContext,
        staging_path: Path,
        metadata: dict[str, Any],
    ) -> V2ProviderOutputDescriptor:
        detected = detect_media_format(staging_path)
        if detected is None or detected.media_type != context.media_type:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result media type could not be verified.",
            )
        return V2ProviderOutputDescriptor(
            output_index=0,
            is_primary=True,
            staging_path=staging_path.relative_to(self._data_dir.resolve()).as_posix(),
            media_type=detected.media_type,
            mime_type=detected.mime_type,
            byte_size=staging_path.stat().st_size,
            sha256=_sha256_file(staging_path),
            provider_asset_id=_optional_text(metadata.get("provider_asset_id")),
        )

    def _validate_context(self, context: V2ProviderExecutionContext) -> None:
        for field in ("workflow_id", "execution_id", "attempt_id"):
            self._validate_id(field, str(getattr(context, field)))
        if not context.slot_id or not context.input_fingerprint:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result context requires a slot and input fingerprint.",
            )

    def _validate_manifest(self, manifest: V2ProviderResultManifest) -> None:
        context = V2ProviderExecutionContext(
            workflow_id=manifest.workflow_id,
            execution_id=manifest.execution_id,
            attempt_id=manifest.attempt_id,
            node_id=manifest.node_id,
            item_id=manifest.item_id,
            slot_id=manifest.slot_id,
            slot_type=manifest.slot_type,
            media_type=manifest.media_type,
            input_fingerprint=manifest.input_fingerprint,
            source_action=manifest.source_action,
            select_generated=manifest.select_generated,
        )
        self._validate_context(context)
        if manifest.provider_result_id != provider_result_id(context, manifest.provider_name):
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result manifest identity does not match its canonical context.",
            )
        if manifest.slot_key != slot_key(manifest.slot_id):
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result manifest slot key does not match its slot identity.",
            )
        primary_outputs = [output for output in manifest.outputs if output.is_primary]
        if manifest.provider_status == "succeeded" and len(primary_outputs) != 1:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Successful provider result manifests require exactly one primary output.",
            )

    @staticmethod
    def _validate_id(field: str, value: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                f"Provider result {field} is not filesystem safe.",
            )

    @staticmethod
    def _atomic_write(path: Path, manifest: V2ProviderResultManifest) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _load_path(path: Path) -> V2ProviderResultManifest:
        try:
            return V2ProviderResultManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise V2ProviderResultStoreError(
                "v2_provider_result_manifest_invalid",
                "Provider result manifest is malformed.",
            ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_snapshot(value: Any, *, key: str | None = None) -> Any:
    normalized_key = key.lower() if isinstance(key, str) else ""
    if _SENSITIVE_KEY.search(normalized_key) or _MEDIA_KEY.search(normalized_key):
        return "[omitted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_snapshot(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_snapshot(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_snapshot(item, key=key) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[omitted]"
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            return "[omitted]"
        if value.startswith(("http://", "https://")):
            parsed = urlsplit(value)
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None
