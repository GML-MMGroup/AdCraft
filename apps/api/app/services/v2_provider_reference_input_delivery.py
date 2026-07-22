from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import AssetBindingV2, AssetVersionMetadataV2
from app.schemas.workflow_v2 import WorkflowAssetVersionV2
from app.services.media_inputs import MediaInputConverter
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_relative_path

PROVIDER_REFERENCE_ERROR_DELIVERY_FAILED = "v2_provider_reference_delivery_failed"
PROVIDER_REFERENCE_ERROR_URL_INVALID = "v2_provider_reference_url_invalid"
PROVIDER_REFERENCE_ERROR_FILE_MISSING = "v2_provider_reference_file_missing"
PROVIDER_REFERENCE_ERROR_UNSUPPORTED = "v2_provider_reference_delivery_unsupported"
PROVIDER_REFERENCE_ERROR_PAYLOAD_TOO_LARGE = "v2_video_reference_payload_too_large"

PROVIDER_REFERENCE_DELIVERY_MODES: dict[str, set[str]] = {
    "volcengine_seedream": {"provider_file_id", "provider_uploaded_url", "image_url", "data_url"},
    "volcengine-seedream": {"provider_file_id", "provider_uploaded_url", "image_url", "data_url"},
    "real_image_provider": {"provider_file_id", "provider_uploaded_url", "image_url", "data_url"},
    "real-image-provider": {"provider_file_id", "provider_uploaded_url", "image_url", "data_url"},
    "volcengine_seedance": {"provider_uploaded_url", "image_url", "data_url"},
    "volcengine-seedance": {"provider_uploaded_url", "image_url", "data_url"},
    "real_video_provider": {"provider_uploaded_url", "image_url", "data_url"},
    "real-video-provider": {"provider_uploaded_url", "image_url", "data_url"},
    "dev_placeholder_image": {"image_url", "data_url"},
    "dev-placeholder-image": {"image_url", "data_url"},
    "dev_placeholder_video": {"image_url", "data_url"},
    "dev-placeholder-video": {"image_url", "data_url"},
}


class V2DeliveredProviderReference(BaseModel):
    asset_id: str
    version_id: str | None = None
    slot_id: str | None = None
    role: str | None = None
    semantic_type: str | None = None
    media_type: str
    mime_type: str
    provider_input_type: Literal[
        "image_url", "data_url", "provider_file_id", "provider_uploaded_url"
    ]
    provider_input_value: str
    source: Literal["public_url", "local_file", "provider_upload"]
    delivery_status: Literal["ready"] = "ready"
    byte_count: int | None = None

    def provider_asset(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "slot_id": self.slot_id,
            "role": self.role,
            "semantic_type": self.semantic_type,
            "media_type": self.media_type,
            "mime_type": self.mime_type,
            "model_input_type": self.provider_input_type,
            "model_input_value": self.provider_input_value,
            "provider_input_type": self.provider_input_type,
            "provider_input_value": self.provider_input_value,
            "source": self.source,
            "delivery_status": self.delivery_status,
            "byte_count": self.byte_count,
        }


class V2ProviderReferenceWireAudit(BaseModel):
    requested_reference_asset_ids: list[str] = Field(default_factory=list)
    delivered_reference_asset_ids: list[str] = Field(default_factory=list)
    serialized_reference_asset_ids: list[str] = Field(default_factory=list)
    submitted_reference_asset_ids: list[str] = Field(default_factory=list)
    provider_request_field: str | None = None
    provider_request_reference_count: int = 0
    request_schema: str | None = None
    omitted_payload: bool = True
    warnings: list[str] = Field(default_factory=list)


class V2ReferenceInputDeliveryFailure(BaseModel):
    asset_id: str
    slot_id: str
    code: str
    message: str
    reason: str
    workflow_id: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    version_id: str | None = None


class V2DeliveredReferenceSet(BaseModel):
    requested_reference_asset_ids: list[str] = Field(default_factory=list)
    references: list[V2DeliveredProviderReference] = Field(default_factory=list)
    failures: list[V2ReferenceInputDeliveryFailure] = Field(default_factory=list)

    @property
    def delivered_reference_asset_ids(self) -> list[str]:
        return [reference.asset_id for reference in self.references]

    @property
    def failed_reference_asset_ids(self) -> list[str]:
        return [failure.asset_id for failure in self.failures]

    @property
    def audit(self) -> dict[str, Any]:
        return {
            "requested_reference_asset_ids": list(self.requested_reference_asset_ids),
            "delivered_reference_asset_ids": self.delivered_reference_asset_ids,
            "failed_reference_asset_ids": self.failed_reference_asset_ids,
            "delivery_types": list(
                dict.fromkeys(reference.provider_input_type for reference in self.references)
            ),
            "failure_reasons": {failure.asset_id: failure.code for failure in self.failures},
            "references": [
                {
                    "asset_id": reference.asset_id,
                    "version_id": reference.version_id,
                    "slot_id": reference.slot_id,
                    "role": reference.role,
                    "semantic_type": reference.semantic_type,
                    "provider_input_type": reference.provider_input_type,
                    "source": reference.source,
                    "byte_count": reference.byte_count,
                }
                for reference in self.references
            ],
            "omitted_payload": True,
            "warnings": [],
        }

    def provider_assets(self) -> list[dict[str, Any]]:
        return [reference.provider_asset() for reference in self.references]

    def raise_for_failures(self, *, required: bool) -> None:
        if not required or not self.failures:
            return
        first = self.failures[0]
        code = first.code or PROVIDER_REFERENCE_ERROR_DELIVERY_FAILED
        raise V2ProviderReferenceDeliveryError(
            code=code,
            message=first.message,
            failures=list(self.failures),
            audit=self.audit,
        )


class V2ProviderReferenceDeliveryError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        failures: list[V2ReferenceInputDeliveryFailure],
        audit: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failures = failures
        self.audit = audit


class V2ProviderReferenceInputDeliveryService:
    def __init__(self, data_dir: Path, *, settings: Settings | None = None) -> None:
        self._data_dir = data_dir
        self._settings = settings or get_settings()
        self._asset_store = V2AssetStoreService(data_dir)
        self._asset_library = V2AssetLibraryRepository(create_v2_database(data_dir))
        self._converter = MediaInputConverter(
            data_dir,
            url_validator=is_provider_compatible_public_url,
            supports_data_url=True,
        )

    def resolve_reference_assets_for_provider(
        self,
        *,
        workflow_id: str,
        asset_ids: list[str],
        provider: str,
        target_media_type: str,
        slot_id: str,
    ) -> V2DeliveredReferenceSet:
        delivery_modes = _delivery_modes_for_provider(provider)
        requested, records = self._reference_records_for_slot(
            workflow_id=workflow_id,
            slot_id=slot_id,
            fallback_asset_ids=asset_ids,
        )
        references: list[V2DeliveredProviderReference] = []
        failures: list[V2ReferenceInputDeliveryFailure] = []
        total_data_url_bytes = 0
        for asset_id, record in zip(requested, records, strict=True):
            if record is None:
                failures.append(
                    _failure(
                        workflow_id=workflow_id,
                        slot_id=slot_id,
                        asset_id=asset_id,
                        code=PROVIDER_REFERENCE_ERROR_DELIVERY_FAILED,
                        reason="asset_metadata_missing",
                    )
                )
                continue
            delivered_or_failure = self._deliver_record(
                workflow_id=workflow_id,
                slot_id=slot_id,
                target_media_type=target_media_type,
                record=record,
                delivery_modes=delivery_modes,
            )
            if isinstance(delivered_or_failure, V2ReferenceInputDeliveryFailure):
                failures.append(delivered_or_failure)
            else:
                if (
                    delivered_or_failure.provider_input_type == "data_url"
                    and delivered_or_failure.byte_count
                ):
                    next_total = total_data_url_bytes + delivered_or_failure.byte_count
                    if next_total > self._settings.v2_provider_reference_total_data_url_bytes:
                        failures.append(
                            _failure(
                                workflow_id=workflow_id,
                                slot_id=slot_id,
                                asset_id=record.asset_id,
                                code=PROVIDER_REFERENCE_ERROR_PAYLOAD_TOO_LARGE,
                                reason="provider_reference_total_payload_too_large",
                                record=record,
                            )
                        )
                        continue
                    total_data_url_bytes = next_total
                references.append(delivered_or_failure)
        return V2DeliveredReferenceSet(
            requested_reference_asset_ids=requested,
            references=references,
            failures=failures,
        )

    def _reference_records_for_slot(
        self,
        *,
        workflow_id: str,
        slot_id: str,
        fallback_asset_ids: list[str],
    ) -> tuple[list[str], list[WorkflowAssetVersionV2 | None]]:
        try:
            bindings = self._asset_library.list_bindings(
                workflow_id=workflow_id,
                target_slot_id=slot_id,
                binding_type="reference_for_slot",
            )
        except V2PersistenceError:
            bindings = ()
        if bindings:
            prompt_bindings = tuple(binding for binding in bindings if binding.use_as_prompt)
            if not prompt_bindings:
                return [], []
            try:
                versions = self._asset_library.resolve_versions(
                    tuple(binding.version_id for binding in prompt_bindings)
                )
            except V2PersistenceError:
                return (
                    [binding.asset_id for binding in prompt_bindings],
                    [None] * len(prompt_bindings),
                )
            return (
                [binding.asset_id for binding in prompt_bindings],
                [
                    _workflow_asset_from_library_binding(binding, version, slot_id)
                    for binding, version in zip(prompt_bindings, versions, strict=True)
                ],
            )

        requested = _ordered_unique(fallback_asset_ids)
        return (
            requested,
            [self._asset_store.find_asset_version(asset_id=asset_id) for asset_id in requested],
        )

    def _deliver_record(
        self,
        *,
        workflow_id: str,
        slot_id: str,
        target_media_type: str,
        record: WorkflowAssetVersionV2,
        delivery_modes: set[str],
    ) -> V2DeliveredProviderReference | V2ReferenceInputDeliveryFailure:
        if record.media_type != "image":
            return _failure(
                workflow_id=workflow_id,
                slot_id=slot_id,
                asset_id=record.asset_id,
                code=PROVIDER_REFERENCE_ERROR_UNSUPPORTED,
                reason=f"{target_media_type}_provider_reference_media_type_{record.media_type}_unsupported",
                record=record,
            )
        provider_file_id = _first_metadata_string(
            record, "provider_file_id", "file_id", "ark_file_id"
        )
        if provider_file_id and "provider_file_id" in delivery_modes:
            return _delivered_reference(
                record,
                input_type="provider_file_id",
                input_value=provider_file_id,
                source="provider_upload",
            )
        provider_uploaded_url = _first_metadata_string(
            record,
            "provider_uploaded_url",
            "provider_url",
            "ark_uploaded_url",
            "uploaded_url",
        )
        if (
            provider_uploaded_url
            and "provider_uploaded_url" in delivery_modes
            and is_provider_compatible_public_url(provider_uploaded_url)
        ):
            return _delivered_reference(
                record,
                input_type="provider_uploaded_url",
                input_value=provider_uploaded_url,
                source="provider_upload",
            )
        public_url = str(record.public_url or "").strip()
        if (
            public_url
            and "image_url" in delivery_modes
            and is_provider_compatible_public_url(public_url)
        ):
            return _delivered_reference(
                record,
                input_type="image_url",
                input_value=public_url,
                source="public_url",
            )
        local_path = str(record.file_path or "").strip()
        if local_path:
            if "data_url" not in delivery_modes:
                return _failure(
                    workflow_id=workflow_id,
                    slot_id=slot_id,
                    asset_id=record.asset_id,
                    code=PROVIDER_REFERENCE_ERROR_UNSUPPORTED,
                    reason="provider_reference_delivery_unsupported",
                    record=record,
                )
            validate_v2_relative_path(local_path, operation="v2-provider-reference-delivery")
            absolute_path = self._data_dir / local_path
            if not absolute_path.exists():
                return _failure(
                    workflow_id=workflow_id,
                    slot_id=slot_id,
                    asset_id=record.asset_id,
                    code=PROVIDER_REFERENCE_ERROR_FILE_MISSING,
                    reason="local_file_missing",
                    record=record,
                )
            converted = self._converter.convert(
                {
                    "asset_id": record.asset_id,
                    "asset_type": record.media_type,
                    "role": _provider_reference_role_from_record(record),
                    "local_path": local_path,
                    "mime_type": _mime_type_for_record(record),
                    "source": "v2_asset_store",
                    "semantic_type": record.semantic_type,
                    "slot_id": record.slot_id,
                    "version_id": record.version_id,
                }
            )
            if converted.get("model_input_type") == "data_url" and isinstance(
                converted.get("model_input_value"), str
            ):
                data_url = str(converted["model_input_value"])
                byte_count = len(data_url.encode("utf-8"))
                if byte_count > self._settings.v2_provider_reference_max_data_url_bytes:
                    return _failure(
                        workflow_id=workflow_id,
                        slot_id=slot_id,
                        asset_id=record.asset_id,
                        code=PROVIDER_REFERENCE_ERROR_PAYLOAD_TOO_LARGE,
                        reason="provider_reference_payload_too_large",
                        record=record,
                    )
                return _delivered_reference(
                    record,
                    input_type="data_url",
                    input_value=data_url,
                    source="local_file",
                    byte_count=byte_count,
                )
        if public_url:
            return _failure(
                workflow_id=workflow_id,
                slot_id=slot_id,
                asset_id=record.asset_id,
                code=PROVIDER_REFERENCE_ERROR_URL_INVALID,
                reason="provider_url_not_externally_usable",
                record=record,
            )
        return _failure(
            workflow_id=workflow_id,
            slot_id=slot_id,
            asset_id=record.asset_id,
            code=PROVIDER_REFERENCE_ERROR_DELIVERY_FAILED,
            reason="no_provider_compatible_reference_input",
            record=record,
        )


def is_provider_compatible_public_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname.lower() in {"localhost", "0.0.0.0"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def is_provider_compatible_model_input(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("data:image/") or is_provider_compatible_public_url(stripped)


def _delivered_reference(
    record: WorkflowAssetVersionV2,
    *,
    input_type: Literal["image_url", "data_url", "provider_file_id", "provider_uploaded_url"],
    input_value: str,
    source: Literal["public_url", "local_file", "provider_upload"],
    byte_count: int | None = None,
) -> V2DeliveredProviderReference:
    return V2DeliveredProviderReference(
        asset_id=record.asset_id,
        version_id=record.version_id,
        slot_id=record.slot_id,
        role=_provider_reference_role_from_record(record),
        semantic_type=record.semantic_type,
        media_type=record.media_type,
        mime_type=_mime_type_for_record(record),
        provider_input_type=input_type,
        provider_input_value=input_value,
        source=source,
        byte_count=byte_count,
    )


def _failure(
    *,
    workflow_id: str,
    slot_id: str,
    asset_id: str,
    code: str,
    reason: str,
    record: WorkflowAssetVersionV2 | None = None,
) -> V2ReferenceInputDeliveryFailure:
    return V2ReferenceInputDeliveryFailure(
        workflow_id=workflow_id,
        node_id=record.node_id if record is not None else None,
        item_id=record.item_id if record is not None else None,
        slot_id=slot_id,
        asset_id=asset_id,
        version_id=record.version_id if record is not None else None,
        code=code,
        reason=reason,
        message=(
            "V2 provider reference delivery failed "
            f"workflow_id={workflow_id} slot_id={slot_id} asset_id={asset_id} reason={reason}"
        ),
    )


def _provider_reference_role_from_record(record: WorkflowAssetVersionV2) -> str | None:
    semantic_type = str(record.semantic_type or "").strip()
    if semantic_type.startswith("shot_cell") or semantic_type == "storyboard_image":
        return "storyboard"
    if semantic_type.startswith("product"):
        return "product_reference"
    if semantic_type.startswith("character"):
        return "character_turnaround"
    if semantic_type.startswith("scene"):
        return "scene_reference"
    return None


def _mime_type_for_record(record: WorkflowAssetVersionV2) -> str:
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    value = metadata.get("mime_type") or metadata.get("content_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    suffix = Path(record.file_path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _ordered_unique(values: list[str]) -> list[str]:
    normalized = [value for value in (str(raw).strip() for raw in values) if value]
    return list(dict.fromkeys(normalized))


def _workflow_asset_from_library_binding(
    binding: AssetBindingV2,
    version: AssetVersionMetadataV2,
    slot_id: str,
) -> WorkflowAssetVersionV2:
    metadata = dict(version.metadata)
    metadata["mime_type"] = version.mime_type
    metadata["reference_role"] = binding.reference_role
    semantic_type = metadata.get("semantic_type")
    return WorkflowAssetVersionV2(
        asset_id=version.asset_id,
        version_id=version.version_id,
        media_type=_media_type_from_mime_type(version.mime_type),
        source_type="generated",
        file_path=version.storage_key,
        public_url=f"/media/{version.storage_key}",
        workflow_id=binding.workflow_id,
        node_id=binding.target_node_id,
        item_id=binding.target_item_id,
        slot_id=slot_id,
        semantic_type=semantic_type if isinstance(semantic_type, str) else None,
        library_entity_id=binding.source_entity_id,
        created_at=version.created_at,
        metadata=metadata,
    )


def _media_type_from_mime_type(mime_type: str) -> Literal["image", "video", "audio", "text"]:
    normalized = mime_type.lower()
    if normalized.startswith("image/"):
        return "image"
    if normalized.startswith("video/"):
        return "video"
    if normalized.startswith("audio/"):
        return "audio"
    return "text"


def _delivery_modes_for_provider(provider: str) -> set[str]:
    return set(PROVIDER_REFERENCE_DELIVERY_MODES.get(provider, set()))


def _first_metadata_string(record: WorkflowAssetVersionV2, *keys: str) -> str | None:
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
