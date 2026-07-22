"""Safe, pinned installation of a Recommended Assets catalog archive."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from typing import Literal
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import (
    AssetCatalogRecordV2,
    AssetEntityCreate,
    AssetEntityMemberCreate,
    AssetRecordCreate,
    AssetVersionCreate,
    RecommendedCatalogStatusResponseV2,
)
from app.services.v2_storage_adapter import StorageAdapter

ArchiveFetcher = Callable[[str, Path], object]


class V2AssetCatalogError(Exception):
    """A catalog failure with a stable public error code and safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CatalogLicense(_CatalogModel):
    source_url: str = Field(min_length=1)
    attribution: str = Field(min_length=1)


class _CatalogMember(_CatalogModel):
    member_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    is_primary: bool = False
    is_default_reference: bool = False
    sort_order: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    mime_type: Literal["image/png", "image/jpeg"]
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    license_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_path(self) -> _CatalogMember:
        _safe_archive_path(self.path)
        return self


class _CatalogEntity(_CatalogModel):
    entity_id: str = Field(min_length=1)
    entity_type: Literal["character", "scene"]
    library_category: Literal["characters", "scenes"]
    display_name: str = Field(min_length=1)
    description: str = ""
    tags: tuple[str, ...] = ()
    members: tuple[_CatalogMember, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_members(self) -> _CatalogEntity:
        if len({member.member_id for member in self.members}) != len(self.members):
            raise ValueError("member IDs must be unique")
        if len({member.sort_order for member in self.members}) != len(self.members):
            raise ValueError("member order must be unique")
        return self


class _CatalogManifest(_CatalogModel):
    catalog_id: str = Field(min_length=1)
    catalog_key: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    archive_url: str = Field(min_length=1)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_archive_bytes: int = Field(ge=1)
    max_member_count: int = Field(ge=1)
    licenses: dict[str, _CatalogLicense] = Field(min_length=1)
    entities: tuple[_CatalogEntity, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_references(self) -> _CatalogManifest:
        if not self.archive_url.startswith("https://"):
            raise ValueError("archive URL must use HTTPS")
        if len({entity.entity_id for entity in self.entities}) != len(self.entities):
            raise ValueError("entity IDs must be unique")
        members = [member for entity in self.entities for member in entity.members]
        if len(members) > self.max_member_count:
            raise ValueError("member count exceeds catalog limit")
        if len({member.path for member in members}) != len(members):
            raise ValueError("archive member paths must be unique")
        if len({member.asset_id for member in members}) != len(members):
            raise ValueError("asset IDs must be unique")
        if len({member.version_id for member in members}) != len(members):
            raise ValueError("version IDs must be unique")
        for member in members:
            if member.license_id not in self.licenses:
                raise ValueError("member license is not declared")
        return self


class V2AssetCatalogService:
    """Validate, install, and report one pinned Recommended Assets catalog."""

    def __init__(
        self,
        *,
        data_dir: Path,
        repository: V2AssetLibraryRepository,
        manifest_path: Path,
        archive_fetcher: ArchiveFetcher | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._repository = repository
        self._manifest_path = manifest_path
        self._archive_fetcher = archive_fetcher or _download_archive
        self._storage = StorageAdapter(data_dir)

    def get_recommended_status(self) -> RecommendedCatalogStatusResponseV2:
        """Return durable status for the pinned manifest without starting installation."""

        manifest = self._load_manifest()
        return self._status_for_manifest(manifest)

    def prepare_recommended_install(
        self,
    ) -> tuple[_CatalogManifest, RecommendedCatalogStatusResponseV2]:
        """Validate the manifest and durably record one pending installation."""

        manifest = self._load_manifest()
        status = self._status_for_manifest(manifest)
        if status.status == "ready":
            return manifest, status
        self._persist_status(manifest, status="downloading", progress_current=0)
        return manifest, self._status_for_manifest(manifest)

    def install_prepared_catalog(
        self,
        manifest: _CatalogManifest,
    ) -> RecommendedCatalogStatusResponseV2:
        """Install a manifest previously validated by the application coordinator."""

        staging_dir = Path(mkdtemp(prefix="recommended-catalog-", dir=self._data_dir / "v2"))
        try:
            archive_path = staging_dir / "catalog.zip"
            self._archive_fetcher(manifest.archive_url, archive_path)
            self._verify_archive(archive_path, manifest)
            self._persist_status(manifest, status="verifying", progress_current=0)
            verified_members = self._verify_members(archive_path, staging_dir, manifest)
            self._persist_status(
                manifest,
                status="installing",
                progress_current=len(verified_members),
            )
            published_members = self._publish_members(verified_members)
            self._commit_catalog(manifest, published_members)
            return _status_from_catalog(
                _catalog_record(
                    manifest,
                    status="ready",
                    progress_current=len(published_members),
                    installed_at=_utc_now(),
                )
            )
        except V2AssetCatalogError as error:
            self._persist_failed_status(manifest, error)
            return self._status_for_manifest(manifest)
        except (OSError, BadZipFile):
            failure = V2AssetCatalogError(
                "recommended_catalog_download_failed",
                "Catalog installation could not be completed.",
            )
            self._persist_failed_status(manifest, failure)
            return self._status_for_manifest(manifest)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _status_for_manifest(
        self,
        manifest: _CatalogManifest,
    ) -> RecommendedCatalogStatusResponseV2:
        try:
            catalog = self._repository.get_catalog(manifest.catalog_id)
        except V2PersistenceError as error:
            if error.code != "asset_catalog_not_found":
                raise V2AssetCatalogError(
                    "recommended_catalog_status_unavailable", "Catalog status is unavailable."
                ) from error
            return _status_from_catalog(_catalog_record(manifest, status="not_installed"))
        return _status_from_catalog(catalog)

    def install_recommended_catalog(self) -> RecommendedCatalogStatusResponseV2:
        """Synchronously install the pinned manifest; callers schedule it outside requests."""

        manifest, status = self.prepare_recommended_install()
        if status.status == "ready":
            return status
        return self.install_prepared_catalog(manifest)

    def _load_manifest(self) -> _CatalogManifest:
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            return _CatalogManifest.model_validate(payload)
        except (OSError, ValueError, ValidationError) as error:
            raise V2AssetCatalogError(
                "recommended_catalog_manifest_invalid", "Catalog manifest is invalid."
            ) from error

    def _verify_archive(self, archive_path: Path, manifest: _CatalogManifest) -> None:
        if not archive_path.is_file() or archive_path.stat().st_size > manifest.max_archive_bytes:
            raise V2AssetCatalogError(
                "recommended_catalog_checksum_mismatch", "Catalog archive could not be verified."
            )
        if _sha256(archive_path) != manifest.archive_sha256:
            raise V2AssetCatalogError(
                "recommended_catalog_checksum_mismatch", "Catalog archive could not be verified."
            )

    def _verify_members(
        self,
        archive_path: Path,
        staging_dir: Path,
        manifest: _CatalogManifest,
    ) -> tuple[tuple[_CatalogMember, Path], ...]:
        members_by_path = {
            member.path: member for entity in manifest.entities for member in entity.members
        }
        try:
            with ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if len(infos) != len(members_by_path):
                    raise _unsafe_archive_error()
                info_by_path: dict[str, ZipInfo] = {}
                for info in infos:
                    _validate_zip_info(info)
                    if info.filename not in members_by_path:
                        raise _unsafe_archive_error()
                    info_by_path[info.filename] = info
                if set(info_by_path) != set(members_by_path):
                    raise _unsafe_archive_error()

                verified: list[tuple[_CatalogMember, Path]] = []
                for member_path, member in members_by_path.items():
                    info = info_by_path[member_path]
                    if info.file_size != member.size_bytes:
                        raise _member_invalid_error()
                    output_path = _staging_member_path(staging_dir, member.path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, output_path.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    if _sha256(output_path) != member.sha256:
                        raise _member_invalid_error()
                    _validate_image_metadata(output_path, member)
                    verified.append((member, output_path))
        except V2AssetCatalogError:
            raise
        except (BadZipFile, OSError, ValueError) as error:
            raise _unsafe_archive_error() from error
        return tuple(verified)

    def _publish_members(
        self,
        verified_members: tuple[tuple[_CatalogMember, Path], ...],
    ) -> tuple[tuple[_CatalogMember, str], ...]:
        published: list[tuple[_CatalogMember, str]] = []
        for member, source_path in verified_members:
            extension = PurePosixPath(member.path).suffix.lstrip(".")
            try:
                storage_key = self._storage.publish_verified_file(
                    source_path, member.sha256, extension
                )
            except V2PersistenceError as error:
                raise V2AssetCatalogError(
                    "recommended_catalog_member_invalid", "Catalog media member is invalid."
                ) from error
            published.append((member, storage_key))
        return tuple(published)

    def _commit_catalog(
        self,
        manifest: _CatalogManifest,
        published_members: tuple[tuple[_CatalogMember, str], ...],
    ) -> None:
        member_storage = {
            member.member_id: storage_key for member, storage_key in published_members
        }
        now = _utc_now()
        try:
            with self._repository.database.engine.begin() as connection:
                self._repository.upsert_catalog(
                    _catalog_record(
                        manifest,
                        status="ready",
                        progress_current=len(published_members),
                        installed_at=now,
                    ),
                    connection=connection,
                )
                for entity in manifest.entities:
                    members: list[AssetEntityMemberCreate] = []
                    for member in entity.members:
                        self._repository.import_asset_version(
                            AssetRecordCreate(
                                asset_id=member.asset_id,
                                media_type="image",
                                source_type="recommended",
                                display_name=member.display_name,
                            ),
                            AssetVersionCreate(
                                version_id=member.version_id,
                                asset_id=member.asset_id,
                                storage_key=member_storage[member.member_id],
                                sha256=member.sha256,
                                size_bytes=member.size_bytes,
                                mime_type=member.mime_type,
                                width=member.width,
                                height=member.height,
                                metadata={
                                    "catalog_id": manifest.catalog_id,
                                    "license_id": member.license_id,
                                    "source_url": manifest.licenses[member.license_id].source_url,
                                    "attribution": manifest.licenses[member.license_id].attribution,
                                },
                            ),
                            connection=connection,
                        )
                        members.append(
                            AssetEntityMemberCreate(
                                member_id=member.member_id,
                                asset_id=member.asset_id,
                                version_id=member.version_id,
                                semantic_type=member.semantic_type,
                                is_primary=member.is_primary,
                                is_default_reference=member.is_default_reference,
                                sort_order=member.sort_order,
                            )
                        )
                    self._repository.create_entity(
                        AssetEntityCreate(
                            entity_id=entity.entity_id,
                            scope="recommended",
                            entity_type=entity.entity_type,
                            library_category=entity.library_category,
                            display_name=entity.display_name,
                            description=entity.description,
                            tags=entity.tags,
                            catalog_id=manifest.catalog_id,
                        ),
                        members=tuple(members),
                        connection=connection,
                    )
        except V2PersistenceError as error:
            raise V2AssetCatalogError(
                "recommended_catalog_metadata_commit_failed",
                "Catalog metadata could not be installed.",
            ) from error

    def _persist_status(
        self,
        manifest: _CatalogManifest,
        *,
        status: Literal["downloading", "verifying", "installing"],
        progress_current: int,
    ) -> None:
        self._repository.upsert_catalog(
            _catalog_record(
                manifest,
                status=status,
                progress_current=progress_current,
            )
        )

    def _persist_failed_status(
        self, manifest: _CatalogManifest, error: V2AssetCatalogError
    ) -> None:
        self._repository.upsert_catalog(
            _catalog_record(
                manifest,
                status="failed",
                last_error_code=error.code,
                last_error_message=error.message,
            )
        )


def _catalog_record(
    manifest: _CatalogManifest,
    *,
    status: Literal["not_installed", "downloading", "verifying", "installing", "ready", "failed"],
    progress_current: int = 0,
    installed_at: str | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
) -> AssetCatalogRecordV2:
    now = _utc_now()
    return AssetCatalogRecordV2(
        catalog_id=manifest.catalog_id,
        catalog_key=manifest.catalog_key,
        catalog_version=manifest.catalog_version,
        source_type="recommended_archive",
        manifest_sha256=_sha256(manifest.model_dump_json().encode("utf-8")),
        archive_url=manifest.archive_url,
        archive_sha256=manifest.archive_sha256,
        license_manifest={key: value.model_dump() for key, value in manifest.licenses.items()},
        status=status,
        is_current=True,
        progress_current=progress_current,
        progress_total=sum(len(entity.members) for entity in manifest.entities),
        installed_at=installed_at,
        last_error_code=last_error_code,
        last_error_message=last_error_message,
        created_at=now,
        updated_at=now,
    )


def _status_from_catalog(catalog: AssetCatalogRecordV2) -> RecommendedCatalogStatusResponseV2:
    return RecommendedCatalogStatusResponseV2(
        catalog_key=catalog.catalog_key,
        catalog_version=catalog.catalog_version,
        status=catalog.status,
        progress_current=catalog.progress_current,
        progress_total=catalog.progress_total,
        last_error_code=catalog.last_error_code,
        message=catalog.last_error_message,
    )


def _download_archive(url: str, destination: Path) -> None:
    try:
        with urlopen(url, timeout=30) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except OSError as error:
        raise V2AssetCatalogError(
            "recommended_catalog_download_failed", "Catalog archive could not be downloaded."
        ) from error


def _validate_zip_info(info: ZipInfo) -> None:
    _safe_archive_path(info.filename)
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if info.is_dir() or kind not in {0, stat.S_IFREG}:
        raise _unsafe_archive_error()


def _safe_archive_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("archive member path is unsafe")
    return path


def _staging_member_path(staging_dir: Path, archive_path: str) -> Path:
    path = _safe_archive_path(archive_path)
    return staging_dir / "members" / Path(*path.parts)


def _validate_image_metadata(path: Path, member: _CatalogMember) -> None:
    if member.mime_type == "image/png":
        width, height = _png_dimensions(path)
    else:
        width, height = _jpeg_dimensions(path)
    if (width, height) != (member.width, member.height):
        raise _member_invalid_error()


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise _member_invalid_error()
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _jpeg_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise _member_invalid_error()
    position = 2
    while position + 9 <= len(data):
        if data[position] != 0xFF:
            raise _member_invalid_error()
        marker = data[position + 1]
        position += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = int.from_bytes(data[position : position + 2], "big")
        if length < 2 or position + length > len(data):
            raise _member_invalid_error()
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            return (
                int.from_bytes(data[position + 5 : position + 7], "big"),
                int.from_bytes(data[position + 3 : position + 5], "big"),
            )
        position += length
    raise _member_invalid_error()


def _sha256(path_or_bytes: Path | bytes) -> str:
    if isinstance(path_or_bytes, bytes):
        return hashlib.sha256(path_or_bytes).hexdigest()
    digest = hashlib.sha256()
    with path_or_bytes.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unsafe_archive_error() -> V2AssetCatalogError:
    return V2AssetCatalogError(
        "recommended_catalog_archive_unsafe", "Catalog archive contains an unsafe entry."
    )


def _member_invalid_error() -> V2AssetCatalogError:
    return V2AssetCatalogError(
        "recommended_catalog_member_invalid", "Catalog media member is invalid."
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
