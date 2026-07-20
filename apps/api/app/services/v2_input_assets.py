from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    V2InputAssetUploadView,
    WorkflowAssetVersionV2,
    WorkflowMediaTypeV2,
)
from app.services.agent_trace import utc_now
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import (
    V2DataBoundaryError,
    validate_v2_data_path,
    validate_v2_relative_path,
)


class V2InputAssetError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2InputAssetService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        data_dir: Path | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._data_dir = data_dir or self._settings.media_data_dir
        self._asset_store = V2AssetStoreService(self._data_dir)

    def upload_pre_workflow_assets(
        self,
        *,
        files: list[UploadFile],
        intent: str,
        display_name: str | None = None,
        tags: list[str] | None = None,
    ) -> list[WorkflowAssetVersionV2]:
        if not files:
            raise V2InputAssetError("upload_file_required")
        semantic_type = _semantic_type_for_intent(intent)
        return [
            self.save_uploaded_asset(
                file=file,
                semantic_type=semantic_type,
                display_name=display_name,
                tags=tags,
                workflow_id=None,
                node_id=None,
                item_id=None,
                slot_id=None,
                intent=intent,
            )
            for file in files
        ]

    def save_uploaded_asset(
        self,
        *,
        file: UploadFile,
        semantic_type: str,
        display_name: str | None = None,
        tags: list[str] | None = None,
        workflow_id: str | None = None,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        intent: str | None = None,
        source_type: str = "upload",
    ) -> WorkflowAssetVersionV2:
        return self.save_asset_bytes(
            body=file.file.read(),
            filename=file.filename or "",
            content_type=file.content_type or "",
            semantic_type=semantic_type,
            display_name=display_name,
            tags=tags,
            workflow_id=workflow_id,
            node_id=node_id,
            item_id=item_id,
            slot_id=slot_id,
            intent=intent,
            source_type=source_type,
        )

    def save_asset_bytes(
        self,
        *,
        body: bytes,
        filename: str,
        content_type: str,
        semantic_type: str,
        display_name: str | None = None,
        tags: list[str] | None = None,
        workflow_id: str | None = None,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        intent: str | None = None,
        source_type: str = "upload",
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowAssetVersionV2:
        media_type = _media_type_for_file(filename, content_type)
        if intent:
            _validate_intent_media(intent, media_type)
        if _upload_limit(self._settings, media_type) is not None and len(body) > int(
            _upload_limit(self._settings, media_type) or 0
        ):
            raise V2InputAssetError("upload_file_too_large")
        asset_id = f"asset_{uuid4().hex[:12]}"
        version_id = f"ver_{uuid4().hex[:12]}"
        safe_filename = _safe_filename(filename, media_type)
        suffix = Path(safe_filename).suffix or _extension_for_media_type(media_type)
        relative_path = Path("assets") / "originals" / asset_id / f"{version_id}{suffix}"
        output_path = validate_v2_data_path(
            self._data_dir,
            self._data_dir / relative_path,
            operation="v2-input-asset-upload",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(body)
        record = WorkflowAssetVersionV2(
            asset_id=asset_id,
            version_id=version_id,
            media_type=media_type,
            source_type=source_type,  # type: ignore[arg-type]
            file_path=relative_path.as_posix(),
            public_url=f"/media/{relative_path.as_posix()}",
            workflow_id=workflow_id,
            node_id=node_id,
            item_id=item_id,
            slot_id=slot_id,
            semantic_type=semantic_type,
            created_by="v2-input-upload",
            created_at=utc_now().isoformat(),
            metadata={
                **dict(metadata or {}),
                "display_name": _display_name(display_name, safe_filename),
                "original_filename": safe_filename,
                "content_type": content_type,
                "tags": list(tags or []),
            },
        )
        return self._asset_store.save_asset_version(record)


def input_asset_view(record: WorkflowAssetVersionV2) -> V2InputAssetUploadView:
    return V2InputAssetUploadView(
        asset_id=record.asset_id,
        version_id=record.version_id,
        locator=asset_locator(record.asset_id, record.version_id),
        media_type=record.media_type,
        semantic_type=record.semantic_type or "",
        source_type=record.source_type,
        public_url=record.public_url,
        display_name=_display_name(
            str(record.metadata.get("display_name") or ""),
            Path(record.file_path).name,
        ),
    )


def asset_locator(asset_id: str, version_id: str) -> str:
    return f"asset:{asset_id}@{version_id}"


def validate_assets_relative_file(data_dir: Path, raw_path: str) -> Path:
    if raw_path.startswith(("http://", "https://")):
        raise V2InputAssetError("remote_reference_registration_not_supported")
    path = Path(raw_path)
    if not path.is_absolute() and path.parts and path.parts[0] == "data":
        path = Path(*path.parts[1:])
    candidate = path if path.is_absolute() else data_dir / path
    try:
        resolved = validate_v2_data_path(
            data_dir,
            candidate,
            operation="v2-register-reference-file",
        )
    except V2DataBoundaryError as exc:
        raise V2InputAssetError(exc.code, str(exc)) from exc
    relative = resolved.relative_to(data_dir.resolve())
    if not relative.parts or relative.parts[0] != "assets":
        raise V2InputAssetError("v2_data_boundary_violation")
    validate_v2_relative_path(relative, operation="v2-register-reference-file")
    if not resolved.exists():
        raise V2InputAssetError("asset_not_found")
    return relative


def _semantic_type_for_intent(intent: str) -> str:
    mapping = {
        "product_reference": "product_reference",
        "style_reference": "style_reference",
        "generic_reference": "generic_reference",
    }
    if intent not in mapping:
        raise V2InputAssetError("input_asset_intent_incompatible")
    return mapping[intent]


def _validate_intent_media(intent: str, media_type: str) -> None:
    allowed = {
        "product_reference": {"image"},
        "style_reference": {"image", "video", "audio"},
        "generic_reference": {"image", "video", "audio"},
    }
    if media_type not in allowed.get(intent, set()):
        raise V2InputAssetError("unsupported_upload_media_type")


def _media_type_for_upload(file: UploadFile) -> WorkflowMediaTypeV2:
    return _media_type_for_file(file.filename or "", file.content_type or "")


def _media_type_for_file(filename: str, raw_content_type: str) -> WorkflowMediaTypeV2:
    content_type = raw_content_type.lower()
    if not content_type:
        guessed, _ = mimetypes.guess_type(filename)
        content_type = (guessed or "").lower()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    raise V2InputAssetError("unsupported_upload_media_type")


def _upload_limit(settings: Settings, media_type: str) -> int | None:
    return {
        "image": settings.upload_image_max_bytes,
        "video": settings.upload_video_max_bytes,
        "audio": settings.upload_audio_max_bytes,
    }.get(media_type)


def _safe_filename(filename: str | None, media_type: str) -> str:
    candidate = Path(filename or f"upload{_extension_for_media_type(media_type)}").name
    candidate = candidate.strip().replace("\\", "_").replace("/", "_")
    return candidate or f"upload{_extension_for_media_type(media_type)}"


def _extension_for_media_type(media_type: str) -> str:
    return {"image": ".png", "video": ".mp4", "audio": ".mp3"}.get(media_type, ".bin")


def _display_name(display_name: str | None, filename: str) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    stem = Path(filename).stem.strip()
    return stem or "Uploaded Asset"
