"""Canonical project-media and image-library operations for Agent Canvas."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_runtime import (
    GeneratedAssetProvenanceV2,
    PublishedMediaFactsV2,
)
from app.schemas.agent_canvas_runtime_authority import (
    PreparedContentObjectV2,
    PreparedNodeResultV2,
)
from app.schemas.agent_canvas_video_parameters import VideoParameterNormalizationV2
from app.schemas.v2_asset_library import (
    AssetEntityCreate,
    AssetEntityMemberCreate,
    AssetEntityMemberV2,
    AssetLibraryCategoryV2,
    AssetLibraryEntityDetailV2,
    AssetLibraryEntityResponseV2,
    AssetLibraryMemberResponseV2,
    AssetRecordCreate,
    AssetVersionCreate,
    AssetVersionMetadataV2,
)
from app.services.v2_storage_adapter import StorageAdapter
from app.services.v2_asset_renditions import V2AssetRenditionService
from app.services.agent_canvas_asset_reference_resolver import (
    AgentCanvasAssetReferenceResolver,
)
from app.services.v2_final_composition_renderer import V2MediaProbe, V2MediaProbeResult


MediaFactsProbe = Callable[[Path, str], V2MediaProbeResult]
AssetVersionPublishedCallback = Callable[[AssetVersionMetadataV2], object]
PreparedObjectCallback = Callable[[PreparedNodeResultV2], object]


@dataclass(frozen=True)
class AssetContentResponse:
    body: bytes
    status_code: int
    media_type: str
    headers: dict[str, str]


def deterministic_media_facts_probe(path: Path, media_type: str) -> V2MediaProbeResult:
    """Probe deterministic Mock output while keeping the test path bounded."""

    return V2MediaProbe()(path, media_type)


class AgentCanvasAssetService:
    """Reuse V2 SQLite metadata and content-addressed storage for canvas media."""

    def __init__(
        self,
        data_dir: Path,
        assets: V2AssetLibraryRepository,
        workflows: AgentCanvasWorkflowRepository,
        *,
        media_facts_probe: MediaFactsProbe | None = None,
        rendition_service: V2AssetRenditionService | None = None,
        on_version_published: AssetVersionPublishedCallback | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._assets = assets
        self._workflows = workflows
        self._storage = StorageAdapter(data_dir)
        self._reference_resolver = AgentCanvasAssetReferenceResolver(data_dir, assets)
        self._media_facts_probe = media_facts_probe or V2MediaProbe()
        self._renditions = rendition_service or V2AssetRenditionService(data_dir)
        self._on_version_published = on_version_published

    def upload_bytes(
        self,
        workflow_id: str,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
        title: str,
        media_type: str,
        idempotency_key: str,
        source_semantic_role: str | None = None,
    ) -> ProjectAssetSummaryV2:
        _validate_upload(media_type, mime_type, content, idempotency_key)
        asset_id = _stable_identifier("asset", workflow_id, idempotency_key)
        version_id = f"version_{asset_id}"
        checksum = hashlib.sha256(content).hexdigest()
        existing = self._assets.find_version(asset_id=asset_id)
        if existing is not None:
            if (
                existing.sha256 != checksum
                or existing.mime_type != mime_type
                or existing.metadata.get("display_name") != title
            ):
                raise V2PersistenceError(
                    "idempotency_conflict",
                    "Idempotency key was reused with different upload content.",
                    stage="agent_canvas_asset_service",
                )
            self._notify_version_published(existing)
            return self._asset_summary(existing)

        extension = _extension(filename, mime_type)
        staging = self._data_dir / "v2" / "staging" / f"{uuid4().hex}.{extension}.upload"
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(content)
        storage_key = self._storage.publish_verified_file(staging, checksum, extension)
        version = self._assets.create_asset_version(
            AssetRecordCreate(
                asset_id=asset_id,
                media_type=media_type,
                source_type="upload",
                display_name=title,
            ),
            AssetVersionCreate(
                version_id=version_id,
                asset_id=asset_id,
                storage_key=storage_key,
                sha256=checksum,
                size_bytes=len(content),
                mime_type=mime_type,
                source_workflow_id=workflow_id,
                metadata={
                    "display_name": title,
                    "original_filename": Path(filename).name,
                    "source_type": "upload",
                    "source_semantic_role": source_semantic_role,
                },
            ),
        )
        self._notify_version_published(version)
        return self._asset_summary(version)

    def resolve_asset(self, asset_id: str) -> ProjectAssetSummaryV2:
        version = self._assets.find_version(asset_id=asset_id)
        if version is None:
            raise V2PersistenceError(
                "asset_not_found",
                "Asset was not found.",
                stage="agent_canvas_asset_service",
            )
        verified = self._reference_resolver.resolve_bound_asset(asset_id, version.version_id)
        return self._asset_summary(verified.metadata)

    def resolve_asset_version(
        self,
        asset_id: str,
        version_id: str,
    ) -> ProjectAssetSummaryV2:
        try:
            verified = self._reference_resolver.resolve_bound_asset(asset_id, version_id)
        except V2PersistenceError as error:
            if error.code == "canvas_asset_reference_version_required":
                raise V2PersistenceError(
                    "asset_version_not_found",
                    "Asset version was not found.",
                    stage="agent_canvas_asset_service",
                ) from error
            raise
        return self._asset_summary(verified.metadata)

    def resolve_target_asset(
        self,
        workflow_id: str,
        asset_id: str,
    ) -> ProjectAssetSummaryV2:
        version = self._assets.find_version(asset_id=asset_id)
        if version is None or (
            version.source_workflow_id is not None and version.source_workflow_id != workflow_id
        ):
            raise V2PersistenceError(
                "target_not_found",
                "Target was not found.",
                stage="agent_canvas_asset_service",
            )
        return self._asset_summary(version)

    def resolve_target_asset_version(
        self,
        workflow_id: str,
        asset_id: str,
        version_id: str,
    ) -> ProjectAssetSummaryV2:
        verified = self._reference_resolver.resolve_bound_asset(asset_id, version_id)
        version = verified.metadata
        if version.source_workflow_id is not None and version.source_workflow_id != workflow_id:
            raise V2PersistenceError(
                "target_not_found",
                "Target was not found.",
                stage="agent_canvas_asset_service",
            )
        return self._asset_summary(version)

    def resolve_asset_path(self, asset_id: str) -> Path:
        """Resolve a registered asset to its canonical local object path."""

        version = self._assets.find_version(asset_id=asset_id)
        if version is None:
            raise V2PersistenceError(
                "asset_not_found",
                "Asset was not found.",
                stage="agent_canvas_asset_service",
            )
        path = self._storage.resolve_local_path(version.storage_key)
        if not path.is_file():
            raise V2PersistenceError(
                "asset_not_ready",
                "Asset content is unavailable.",
                stage="agent_canvas_asset_service",
            )
        return path

    def resolve_asset_version_path(self, asset_id: str, version_id: str) -> Path:
        """Resolve one exact immutable AssetVersion to a readable object path."""

        return self._reference_resolver.resolve_bound_asset(asset_id, version_id).path

    def publish_generated_bytes(
        self,
        workflow_id: str,
        *,
        node_id: str,
        execution_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        fingerprint: str,
        source_type: str = "generated",
        source_semantic_role: str | None = None,
        publication_metadata: Mapping[str, object] | None = None,
        require_native_audio: bool = False,
    ) -> ProjectAssetSummaryV2:
        """Idempotently publish validated executor bytes to unified storage."""

        if not _valid_generated_media(content, mime_type):
            raise V2PersistenceError(
                "provider_output_invalid",
                "Provider output is empty or has an unsupported media type.",
                stage="agent_canvas_asset_service",
            )
        asset_id = _stable_identifier("asset", workflow_id, node_id, fingerprint)
        version_id = f"version_{asset_id}"
        checksum = hashlib.sha256(content).hexdigest()
        existing = self._assets.find_version(asset_id=asset_id)
        if existing is not None:
            if existing.sha256 != checksum or existing.mime_type != mime_type:
                raise V2PersistenceError(
                    "provider_publication_conflict",
                    "The node-run fingerprint resolved to different output bytes.",
                    stage="agent_canvas_asset_service",
                )
            self._notify_version_published(existing)
            return self._asset_summary(existing)
        extension = _extension(filename, mime_type)
        staging = (
            self._data_dir
            / "v2"
            / "runs"
            / workflow_id
            / "staging"
            / f"{asset_id}.{extension}.part"
        )
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(content)
        facts = self._probe_generated_media(
            staging,
            mime_type=mime_type,
            checksum=checksum,
            size_bytes=len(content),
            require_native_audio=require_native_audio,
        )
        storage_key = self._storage.publish_verified_file(staging, checksum, extension)
        workflow = self._workflows.get_workflow(workflow_id)
        provenance = {
            **dict(publication_metadata or {}),
            "project_id": workflow.project_id,
            "workflow_id": workflow_id,
            "node_id": node_id,
            "execution_id": execution_id,
            "checksum": checksum,
            "publication_status": "ready",
            "publication_id": fingerprint,
        }
        measured_facts = facts.model_dump(mode="json")
        if mime_type.startswith("image/") and _image_size_mismatch(
            provenance.get("submitted_media_facts"),
            width=facts.width,
            height=facts.height,
        ):
            warnings = list(provenance.get("media_fact_warnings") or ())
            if "generated_image_size_mismatch" not in warnings:
                warnings.append("generated_image_size_mismatch")
            provenance["media_fact_warnings"] = warnings
        node = next((item for item in workflow.nodes if item.node_id == node_id), None)
        generated_provenance = _generated_provenance(
            provenance,
            workflow_id=workflow_id,
            node_id=node_id,
            execution_id=execution_id,
            node_revision=(node.revision if node is not None else 1),
        )
        provenance.update(
            {
                "published_media_facts": measured_facts,
                "measured_media_facts": measured_facts,
                "generated_asset_provenance": generated_provenance.model_dump(mode="json"),
            }
        )
        version = self._assets.create_asset_version(
            AssetRecordCreate(
                asset_id=asset_id,
                media_type=mime_type.split("/", 1)[0],
                source_type=("generated" if source_type == "editing_export" else source_type),
                display_name=Path(filename).stem,
            ),
            AssetVersionCreate(
                version_id=version_id,
                asset_id=asset_id,
                storage_key=storage_key,
                sha256=checksum,
                size_bytes=len(content),
                mime_type=mime_type,
                width=facts.width,
                height=facts.height,
                duration_seconds=facts.duration_seconds,
                provider=_optional_string(provenance.get("provider")),
                model_id=_optional_string(provenance.get("model_id")),
                source_workflow_id=workflow_id,
                source_node_id=node_id,
                metadata={
                    "display_name": Path(filename).stem,
                    "source_type": source_type,
                    "source_node_id": node_id,
                    "source_execution_id": execution_id,
                    "source_semantic_role": source_semantic_role,
                    "fingerprint": fingerprint,
                    **provenance,
                },
            ),
        )
        self._notify_version_published(version)
        return self._asset_summary(version)

    def _notify_version_published(self, version: AssetVersionMetadataV2) -> None:
        if self._on_version_published is None:
            return
        try:
            self._on_version_published(version)
        except V2PersistenceError:
            # Cover metadata is repairable and must not invalidate published media.
            return

    def prepare_generated_bytes(
        self,
        workflow_id: str,
        *,
        node_id: str,
        execution_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        fingerprint: str,
        source_type: str = "generated",
        source_semantic_role: str | None = None,
        publication_metadata: Mapping[str, object] | None = None,
        require_native_audio: bool = False,
        publication_intent_id: str | None = None,
        before_object_publish: PreparedObjectCallback | None = None,
    ) -> PreparedNodeResultV2:
        """Prepare verified bytes without publishing product Asset metadata."""

        if not _valid_generated_media(content, mime_type):
            raise V2PersistenceError(
                "provider_output_invalid",
                "Provider output is empty or has an unsupported media type.",
                stage="agent_canvas_asset_service",
            )
        checksum = hashlib.sha256(content).hexdigest()
        asset_id = _stable_identifier("asset", workflow_id, node_id, fingerprint)
        version_id = f"version_{asset_id}"
        extension = _extension(filename, mime_type)
        storage_key = self._storage.content_storage_key(checksum, extension)
        workflow = self._workflows.get_workflow(workflow_id)
        node = next((item for item in workflow.nodes if item.node_id == node_id), None)
        metadata = {
            **dict(publication_metadata or {}),
            "display_name": Path(filename).stem,
            "source_type": source_type,
            "source_node_id": node_id,
            "source_execution_id": execution_id,
            "source_semantic_role": source_semantic_role,
            "fingerprint": fingerprint,
            "project_id": workflow.project_id,
            "workflow_id": workflow_id,
            "checksum": checksum,
            "publication_status": "prepared",
            "publication_id": fingerprint,
            "generated_asset_provenance": _generated_provenance(
                dict(publication_metadata or {}),
                workflow_id=workflow_id,
                node_id=node_id,
                execution_id=execution_id,
                node_revision=(node.revision if node is not None else 1),
            ).model_dump(mode="json"),
        }
        planned = PreparedNodeResultV2(
            logical_result_key=fingerprint,
            payload_digest=checksum,
            publication_intent_id=publication_intent_id,
            prepared_object=PreparedContentObjectV2(
                storage_key=storage_key,
                sha256=checksum,
                size_bytes=len(content),
                media_type=mime_type.split("/", 1)[0],
                mime_type=mime_type,
                filename=filename,
                media_facts={},
            ),
            asset_id=asset_id,
            version_id=version_id,
            asset_display_name=Path(filename).stem,
            asset_source_type=("generated" if source_type == "editing_export" else source_type),
            asset_metadata={key: value for key, value in metadata.items() if value is not None},
        )
        if before_object_publish is not None:
            before_object_publish(planned)
        staging = (
            self._data_dir
            / "v2"
            / "runs"
            / workflow_id
            / "staging"
            / f"{asset_id}.{extension}.part"
        )
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(content)
        facts = self._probe_generated_media(
            staging,
            mime_type=mime_type,
            checksum=checksum,
            size_bytes=len(content),
            require_native_audio=require_native_audio,
        )
        published_storage_key = self._storage.publish_verified_file(staging, checksum, extension)
        if published_storage_key != storage_key:
            raise V2PersistenceError(
                "v2_storage_key_invalid",
                "Prepared storage identity changed during publication.",
                stage="agent_canvas_asset_service",
            )
        metadata = {
            **metadata,
            "published_media_facts": facts.model_dump(mode="json"),
            "measured_media_facts": facts.model_dump(mode="json"),
        }
        return PreparedNodeResultV2(
            logical_result_key=fingerprint,
            payload_digest=checksum,
            publication_intent_id=publication_intent_id,
            prepared_object=PreparedContentObjectV2(
                storage_key=storage_key,
                sha256=checksum,
                size_bytes=len(content),
                media_type=mime_type.split("/", 1)[0],
                mime_type=mime_type,
                filename=filename,
                media_facts=facts.model_dump(mode="json"),
            ),
            asset_id=asset_id,
            version_id=version_id,
            asset_display_name=Path(filename).stem,
            asset_source_type=("generated" if source_type == "editing_export" else source_type),
            asset_metadata={key: value for key, value in metadata.items() if value is not None},
        )

    def _probe_generated_media(
        self,
        path: Path,
        *,
        mime_type: str,
        checksum: str,
        size_bytes: int,
        require_native_audio: bool = False,
    ) -> PublishedMediaFactsV2:
        media_type = mime_type.split("/", 1)[0]
        probe = self._media_facts_probe(path, media_type)
        if probe.error is not None:
            raise V2PersistenceError(
                "provider_output_invalid",
                "Provider output could not be probed.",
                stage="agent_canvas_asset_service",
            )
        if media_type == "image" and (probe.width is None or probe.height is None):
            raise V2PersistenceError(
                "provider_output_invalid",
                "Image output is missing measured dimensions.",
                stage="agent_canvas_asset_service",
            )
        if media_type == "video" and (
            probe.width is None
            or probe.height is None
            or probe.duration_seconds is None
            or probe.fps is None
        ):
            raise V2PersistenceError(
                "provider_output_invalid",
                "Video output is missing measured media facts.",
                stage="agent_canvas_asset_service",
            )
        if media_type == "video" and require_native_audio and not probe.has_audio:
            raise V2PersistenceError(
                "video_native_audio_missing",
                "Video output is missing the required native audio stream.",
                stage="agent_canvas_asset_service",
                details={"has_audio": False, "retryable": True},
            )
        if media_type == "audio" and probe.duration_seconds is None:
            raise V2PersistenceError(
                "provider_output_invalid",
                "Audio output is missing a measured duration.",
                stage="agent_canvas_asset_service",
            )
        return PublishedMediaFactsV2(
            width=probe.width,
            height=probe.height,
            duration_seconds=probe.duration_seconds,
            frame_rate=probe.fps,
            has_audio=probe.has_audio,
            checksum=checksum,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )

    def recover_prepared_result(
        self,
        planned: PreparedNodeResultV2,
    ) -> PreparedNodeResultV2:
        """Revalidate one content-addressed object without publishing Asset metadata."""

        prepared_object = planned.prepared_object
        if prepared_object is None:
            raise _publication_object_error()
        path = self._storage.resolve_local_path(prepared_object.storage_key)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != prepared_object.size_bytes
            or not self._storage.content_exists(
                prepared_object.storage_key,
                prepared_object.sha256,
            )
        ):
            raise _publication_object_error()
        effective_parameters = planned.asset_metadata.get("effective_parameters")
        require_native_audio = (
            prepared_object.media_type == "video"
            and isinstance(effective_parameters, dict)
            and effective_parameters.get("generate_audio") is True
        )
        facts = self._probe_generated_media(
            path,
            mime_type=prepared_object.mime_type,
            checksum=prepared_object.sha256,
            size_bytes=prepared_object.size_bytes,
            require_native_audio=require_native_audio,
        )
        recovered = planned.model_copy(
            update={
                "prepared_object": prepared_object.model_copy(
                    update={"media_facts": facts.model_dump(mode="json")}
                ),
                "asset_metadata": {
                    **planned.asset_metadata,
                    "published_media_facts": facts.model_dump(mode="json"),
                    "measured_media_facts": facts.model_dump(mode="json"),
                },
            }
        )
        return PreparedNodeResultV2.model_validate(recovered.model_dump(mode="python"))

    def list_project_assets(self, workflow_id: str) -> tuple[ProjectAssetSummaryV2, ...]:
        return tuple(
            self._asset_summary(version)
            for version in self._assets.list_versions_for_workflow(workflow_id)
        )

    def find_latest_ready_versions(
        self,
        asset_ids: tuple[str, ...],
    ) -> dict[str, AssetVersionMetadataV2]:
        """Resolve selected cover assets without one database read per project."""

        return self._assets.find_latest_ready_versions(asset_ids)

    def find_versions_by_id(
        self,
        version_ids: tuple[str, ...],
    ) -> dict[str, AssetVersionMetadataV2]:
        """Resolve immutable versions without promoting a cover to a newer version."""

        return self._assets.find_versions_by_id(version_ids)

    def validate_asset_backed_node(self, asset_id: str, node_type: str) -> None:
        asset = self.resolve_asset(asset_id)
        if node_type not in {"image", "video", "audio"} or asset.media_type != node_type:
            raise V2PersistenceError(
                "asset_media_incompatible",
                "Asset media type is incompatible with the node type.",
                stage="agent_canvas_asset_service",
            )

    def open_content(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
        range_header: str | None = None,
        download: bool = False,
    ) -> AssetContentResponse:
        version = self._require_ready_version(asset_id, version_id=version_id)
        path = self._storage.resolve_local_path(version.storage_key)
        size = path.stat().st_size
        start, end, partial = _parse_range(range_header, size)
        with path.open("rb") as source:
            source.seek(start)
            body = source.read(end - start + 1)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(body)),
            "Cache-Control": (
                "private, max-age=31536000, immutable"
                if version_id is not None
                else "private, max-age=0, must-revalidate"
            ),
            "ETag": f'"{version.asset_id}:{version.version_id}"',
        }
        if partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{_download_filename(version)}"'
        return AssetContentResponse(
            body=body,
            status_code=206 if partial else 200,
            media_type=version.mime_type,
            headers=headers,
        )

    def open_rendition(
        self,
        asset_id: str,
        version_id: str,
        *,
        kind: str,
        max_dimension: int | None = None,
    ) -> AssetContentResponse:
        """Return one exact version-pinned browser rendition."""

        version = self._require_ready_version(asset_id, version_id=version_id)
        media_type = _media_type_from_mime(version.mime_type)
        if media_type not in {"image", "video"}:
            raise V2PersistenceError(
                "asset_rendition_media_unsupported",
                "Asset rendition media type is unsupported.",
                stage="agent_canvas_asset_service",
            )
        source_path = self._storage.resolve_local_path(version.storage_key)
        rendition = self._renditions.ensure(
            source_path,
            asset_id=asset_id,
            version_id=version_id,
            media_type=media_type,
            kind=kind,
            max_dimension=max_dimension,
        )
        body = rendition.path.read_bytes()
        return AssetContentResponse(
            body=body,
            status_code=200,
            media_type=rendition.media_type,
            headers={
                "Content-Length": str(len(body)),
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"{asset_id}:{version_id}:{kind}'
                + (f":{max_dimension}" if max_dimension is not None else "")
                + '"',
            },
        )

    def list_images(
        self,
        *,
        scope: str,
        category: str | None = None,
    ) -> tuple[AssetLibraryEntityResponseV2, ...]:
        library_category = _library_category(category) if category else None
        page = self._assets.list_entities(
            scope="recommended" if scope == "recommended" else "user",
            category=library_category,
            status="active",
            limit=100,
        )
        return tuple(
            _image_library_entity(self._assets.get_entity(item.entity_id), self._storage)
            for item in page.items
        )

    def save_image_to_library(
        self,
        asset_id: str,
        *,
        category: str,
        display_name: str,
        idempotency_key: str,
    ) -> AssetLibraryEntityDetailV2:
        version = self._require_ready_version(asset_id)
        if not version.mime_type.startswith("image/"):
            raise V2PersistenceError(
                "asset_library_media_incompatible",
                "Only images can be saved to the image library.",
                stage="agent_canvas_asset_service",
            )
        entity_id = _stable_identifier("entity", asset_id, idempotency_key)
        try:
            existing = self._assets.get_entity(entity_id)
        except V2PersistenceError as error:
            if error.code != "asset_library_entity_not_found":
                raise
        else:
            if existing.members[0].asset_id != asset_id:
                raise V2PersistenceError(
                    "idempotency_conflict",
                    "Idempotency key was reused for another asset.",
                    stage="agent_canvas_asset_service",
                )
            return existing
        entity_type = "prop" if category == "prop" else category
        return self._assets.create_entity(
            AssetEntityCreate(
                entity_id=entity_id,
                scope="user",
                entity_type=entity_type,
                library_category=_library_category(category),
                display_name=display_name,
            ),
            members=(
                AssetEntityMemberCreate(
                    member_id=f"member_{uuid4().hex}",
                    asset_id=asset_id,
                    version_id=version.version_id,
                    semantic_type=f"{category}_main",
                    is_primary=True,
                    is_default_reference=True,
                    sort_order=0,
                ),
            ),
        )

    @staticmethod
    def library_category_for_entity_type(entity_type: str) -> str:
        return "props" if entity_type == "product" else _library_category(entity_type)

    def delete_asset(self, asset_id: str) -> None:
        if self._workflows.asset_is_referenced(asset_id):
            raise V2PersistenceError(
                "asset_is_referenced",
                "Referenced assets cannot be permanently deleted.",
                stage="agent_canvas_asset_service",
            )
        storage_keys = self._assets.delete_asset(asset_id)
        for storage_key in storage_keys:
            if self._storage_key_is_shared(storage_key):
                continue
            self._storage.resolve_local_path(storage_key).unlink(missing_ok=True)

    def _require_ready_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> AssetVersionMetadataV2:
        version = self._assets.find_version(asset_id=asset_id, version_id=version_id)
        if (
            version is None
            or version.status != "ready"
            or not self._storage.file_exists(version.storage_key)
        ):
            raise V2PersistenceError(
                "asset_not_ready",
                "Asset content is not ready.",
                stage="agent_canvas_asset_service",
            )
        return version

    def _storage_key_is_shared(self, storage_key: str) -> bool:
        return self._assets.count_versions_with_storage_key(storage_key) > 0

    def _asset_summary(self, version: AssetVersionMetadataV2) -> ProjectAssetSummaryV2:
        workflow_id = version.source_workflow_id
        project_id = None
        if workflow_id is not None:
            project_id = self._workflows.get_workflow(workflow_id).project_id
        return _asset_summary(
            version,
            project_id=project_id,
            workflow_id=workflow_id,
        )


def _valid_generated_media(content: bytes, mime_type: str) -> bool:
    signatures = {
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/jpeg": (b"\xff\xd8\xff",),
        "video/mp4": (b"ftyp",),
        "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
        "audio/wav": (b"RIFF",),
    }
    expected = signatures.get(mime_type)
    if expected is None or not content:
        return False
    if mime_type == "video/mp4":
        return b"ftyp" in content[:32]
    return any(content.startswith(signature) for signature in expected)


def _asset_summary(
    version: AssetVersionMetadataV2,
    *,
    project_id: str | None,
    workflow_id: str | None,
) -> ProjectAssetSummaryV2:
    media_type = _media_type_from_mime(version.mime_type)
    source_type = str(version.metadata.get("source_type") or "generated")
    if source_type not in {
        "upload",
        "generated",
        "recommended",
        "derived",
        "library",
        "editing_export",
    }:
        source_type = "generated"
    rendition_url = None
    if version.status == "ready" and media_type in {"image", "video"}:
        rendition_kind = "preview" if media_type == "image" else "poster"
        rendition_url = f"/api/v2/assets/{version.asset_id}/{rendition_kind}?v={version.version_id}"
    return ProjectAssetSummaryV2(
        asset_id=version.asset_id,
        version_id=version.version_id,
        project_id=project_id,
        workflow_id=workflow_id,
        media_type=media_type,
        source_type=source_type,
        display_name=str(version.metadata.get("display_name") or version.asset_id),
        mime_type=version.mime_type,
        status=version.status,
        size_bytes=version.size_bytes,
        storage_key=version.storage_key,
        # Canvas consumers must receive a derived, version-pinned rendition;
        # source content remains available through media_url for explicit
        # preview/download actions.
        preview_url=rendition_url,
        media_url=f"/api/v2/assets/{version.asset_id}/content",
        width=version.width,
        height=version.height,
        duration_seconds=version.duration_seconds,
        checksum=version.sha256,
        semantic_type=_source_semantic_role(version.metadata),
        source_semantic_role=_source_semantic_role(version.metadata),
        source_node_id=version.source_node_id
        or _optional_string(version.metadata.get("source_node_id")),
        source_execution_id=_optional_string(version.metadata.get("source_execution_id")),
        provider=version.provider,
        model_id=version.model_id,
        prompt_provenance={"prompt": version.prompt} if version.prompt else {},
        actual_media_facts=(
            dict(version.metadata.get("published_media_facts", {}))
            if isinstance(version.metadata.get("published_media_facts"), Mapping)
            else {}
        ),
        generation_provenance=(
            dict(version.metadata.get("generated_asset_provenance", {}))
            if isinstance(version.metadata.get("generated_asset_provenance"), Mapping)
            else {}
        ),
        quality_metadata=version.quality or {},
        created_at=version.created_at,
    )


def _image_library_entity(
    detail: AssetLibraryEntityDetailV2,
    storage: StorageAdapter,
) -> AssetLibraryEntityResponseV2:
    members = tuple(
        _image_library_member(member, storage)
        for member in detail.members
        if member.version is not None
    )
    preview = next(
        (member for member in members if member.is_primary),
        members[0] if members else None,
    )
    preview_version = next(
        (
            member.version
            for member in detail.members
            if member.member_id == (preview.member_id if preview is not None else None)
        ),
        None,
    )
    preview_key = (
        _optional_string(preview_version.metadata.get("preview_storage_key"))
        if preview_version is not None
        else None
    )
    return AssetLibraryEntityResponseV2(
        entity_id=detail.entity_id,
        scope=detail.scope,
        entity_type=detail.entity_type,
        library_category=detail.library_category,
        display_name=detail.display_name,
        description=detail.description,
        tags=detail.tags,
        is_favorite=detail.is_favorite,
        status=detail.status,
        preview_member=preview,
        preview_url=(
            f"/media/{preview_key}"
            if preview_key is not None and storage.file_exists(preview_key)
            else preview.public_url
            if preview is not None
            else None
        ),
        member_count=len(members),
    )


def _image_library_member(
    member: AssetEntityMemberV2,
    storage: StorageAdapter,
) -> AssetLibraryMemberResponseV2:
    version = member.version
    if version is None:
        raise V2PersistenceError(
            "asset_library_member_version_missing",
            "Asset library member version is missing.",
            stage="agent_canvas_asset_service",
        )
    return AssetLibraryMemberResponseV2(
        member_id=member.member_id,
        semantic_type=member.semantic_type,
        asset_id=member.asset_id,
        version_id=member.version_id,
        mime_type=version.mime_type,
        width=version.width,
        height=version.height,
        duration_seconds=version.duration_seconds,
        public_url=(
            f"/api/v2/assets/{member.asset_id}/content"
            if version.status == "ready" and storage.file_exists(version.storage_key)
            else None
        ),
        is_primary=member.is_primary,
        is_default_reference=member.is_default_reference,
        sort_order=member.sort_order,
    )


def _source_semantic_role(metadata: dict[str, object]) -> str | None:
    for key in ("source_semantic_role", "semantic_role", "semantic_type"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _optional_nonnegative_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _generated_provenance(
    metadata: Mapping[str, object],
    *,
    workflow_id: str,
    node_id: str,
    execution_id: str,
    node_revision: int,
) -> GeneratedAssetProvenanceV2:
    prompt_registry_ref = _optional_string(metadata.get("prompt_registry_ref")) or (
        "agent_canvas_provider_prompt_v2"
    )
    return GeneratedAssetProvenanceV2(
        node_run_snapshot_id=(
            _optional_string(metadata.get("node_run_snapshot_id"))
            or f"run_intent_{_stable_identifier('snapshot', execution_id, node_id)}"
        ),
        input_manifest_id=_optional_string(metadata.get("input_manifest_id")),
        parameter_compilation_snapshot_id=_optional_string(
            metadata.get("parameter_compilation_snapshot_id")
        ),
        node_revision=node_revision,
        compiled_prompt_digest=_hex_digest(
            metadata.get("compiled_prompt_digest") or metadata.get("prompt_digest")
        ),
        prompt_registry_ref=prompt_registry_ref,
        prompt_registry_digest=_hex_digest(
            metadata.get("prompt_registry_digest") or prompt_registry_ref
        ),
        provider=_optional_string(metadata.get("provider")) or "unknown",
        model_id=_optional_string(metadata.get("model_id")) or "unknown",
        provider_task_id=_optional_string(metadata.get("provider_task_id")),
        execution_mode=_optional_string(metadata.get("execution_mode")) or "agent_assisted",
        semantic_extraction=(_optional_string(metadata.get("semantic_extraction")) or "agent"),
        requested_parameters=_json_mapping(metadata.get("requested_parameters")),
        effective_parameters=_json_mapping(metadata.get("effective_parameters")),
        normalizations=_generated_normalizations(metadata.get("normalizations")),
        source_asset_version_ids=tuple(
            item
            for item in metadata.get("source_asset_version_ids", ())
            if isinstance(item, str) and item
        )
        if isinstance(metadata.get("source_asset_version_ids"), (list, tuple))
        else (),
    )


def _generated_normalizations(
    value: object,
) -> tuple[str | VideoParameterNormalizationV2, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str | VideoParameterNormalizationV2] = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(VideoParameterNormalizationV2.model_validate(item))
    return tuple(result)


def _image_size_mismatch(
    submitted_facts: object,
    *,
    width: int | None,
    height: int | None,
) -> bool:
    if not isinstance(submitted_facts, Mapping) or width is None or height is None:
        return False
    size = submitted_facts.get("size")
    if not isinstance(size, str):
        return False
    try:
        requested_width, requested_height = (int(part) for part in size.lower().split("x", 1))
    except (TypeError, ValueError):
        return False
    return (requested_width, requested_height) != (width, height)


def _hex_digest(value: object) -> str:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    ):
        return value.lower()
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def _json_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _validate_upload(
    media_type: str,
    mime_type: str,
    content: bytes,
    idempotency_key: str,
) -> None:
    if not content or not idempotency_key:
        raise V2PersistenceError(
            "asset_upload_invalid",
            "Upload content and idempotency key are required.",
            stage="agent_canvas_asset_service",
        )
    if _media_type_from_mime(mime_type) != media_type:
        raise V2PersistenceError(
            "asset_media_incompatible",
            "Declared media type does not match the upload content type.",
            stage="agent_canvas_asset_service",
        )


def _media_type_from_mime(mime_type: str) -> str:
    prefix = mime_type.split("/", 1)[0].lower()
    if prefix not in {"image", "video", "audio"}:
        raise V2PersistenceError(
            "asset_media_type_unsupported",
            "Asset media type is unsupported.",
            stage="agent_canvas_asset_service",
        )
    return prefix


def _extension(filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix and suffix.isalnum() and len(suffix) <= 16:
        return suffix
    guessed = mimetypes.guess_extension(mime_type) or ""
    normalized = guessed.lstrip(".")
    if not normalized:
        raise V2PersistenceError(
            "asset_extension_unsupported",
            "Asset file extension is unsupported.",
            stage="agent_canvas_asset_service",
        )
    return normalized


def _download_filename(version: AssetVersionMetadataV2) -> str:
    display_name = str(version.metadata.get("display_name") or version.asset_id)
    stem = Path(display_name).stem or version.asset_id
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or version.asset_id
    extension = _extension(display_name, version.mime_type)
    return f"{safe_stem}.{extension}"


def _stable_identifier(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _publication_object_error() -> V2PersistenceError:
    return V2PersistenceError(
        "node_result_publication_object_invalid",
        "Prepared media object could not be verified.",
        stage="agent_canvas_asset_service",
        details={"retryable": False},
    )


def _library_category(value: str) -> AssetLibraryCategoryV2:
    categories = {
        "character": "characters",
        "characters": "characters",
        "scene": "scenes",
        "scenes": "scenes",
        "product": "props",
        "prop": "props",
        "props": "props",
    }
    try:
        return categories[value]
    except KeyError as error:
        raise V2PersistenceError(
            "asset_library_category_invalid",
            "Image library category is invalid.",
            stage="agent_canvas_asset_service",
        ) from error


def _parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if value is None:
        return 0, max(0, size - 1), False
    if not value.startswith("bytes=") or "," in value:
        raise V2PersistenceError(
            "asset_range_invalid",
            "Asset byte range is invalid.",
            stage="agent_canvas_asset_service",
        )
    start_text, separator, end_text = value[6:].partition("-")
    if not separator or not start_text.isdigit():
        raise V2PersistenceError(
            "asset_range_invalid",
            "Asset byte range is invalid.",
            stage="agent_canvas_asset_service",
        )
    start = int(start_text)
    end = int(end_text) if end_text.isdigit() else size - 1
    if start >= size or end < start:
        raise V2PersistenceError(
            "asset_range_unsatisfiable",
            "Asset byte range is unsatisfiable.",
            stage="agent_canvas_asset_service",
        )
    return start, min(end, size - 1), True
