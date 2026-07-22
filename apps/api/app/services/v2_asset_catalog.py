"""Zero-copy discovery and SQLite indexing for local Recommended Assets packages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

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
from app.schemas.v2_recommended_catalog import CatalogLicenseManifestV1, CatalogManifestV1


_VERSION_DIRECTORY = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")


class V2AssetCatalogError(Exception):
    """A catalog failure with a stable public error code and safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class CatalogPackageCandidate:
    """One complete extracted package below the configured data boundary."""

    root: Path
    manifest_path: Path
    catalog_version: str
    version_order: tuple[int, int, int]


class V2AssetCatalogService:
    """Validate local catalog packages and commit only their immutable metadata."""

    def __init__(
        self,
        *,
        data_dir: Path,
        repository: V2AssetLibraryRepository,
        catalog_root: Path = Path("assets/catalogs/recommended"),
    ) -> None:
        if catalog_root.is_absolute() or tuple(catalog_root.parts[:3]) != (
            "assets",
            "catalogs",
            "recommended",
        ):
            raise ValueError("recommended catalog root must be data-root-relative")
        self._data_dir = data_dir
        self._repository = repository
        self._catalog_root = data_dir / catalog_root

    def discover_latest_package(self) -> CatalogPackageCandidate | None:
        """Return the highest semantic extracted release without scanning recursively."""

        if not self._catalog_root.is_dir() or self._catalog_root.is_symlink():
            return None
        candidates: list[CatalogPackageCandidate] = []
        for path in self._catalog_root.iterdir():
            match = _VERSION_DIRECTORY.fullmatch(path.name)
            if match is None or not path.is_dir() or path.is_symlink():
                continue
            manifest_path = path / "catalog.json"
            if manifest_path.is_file() and not manifest_path.is_symlink():
                candidates.append(
                    CatalogPackageCandidate(
                        root=path,
                        manifest_path=manifest_path,
                        catalog_version=".".join(match.groups()),
                        version_order=tuple(int(value) for value in match.groups()),
                    )
                )
        return max(candidates, key=lambda candidate: candidate.version_order, default=None)

    def catalog_missing_status(self) -> RecommendedCatalogStatusResponseV2:
        return RecommendedCatalogStatusResponseV2(
            status="catalog_missing",
            message="Recommended assets have not been extracted.",
        )

    def status_for_candidate(
        self, candidate: CatalogPackageCandidate
    ) -> RecommendedCatalogStatusResponseV2:
        """Read the durable ready identity without hashing package media."""

        manifest, manifest_sha256 = self._load_package_manifest(candidate)
        if self._ready_identity_matches(manifest.catalog_version, manifest_sha256):
            return self._status_for_verified_manifest(manifest, manifest_sha256)
        return self._indexing_status(manifest, manifest_sha256)

    def invalid_status(self, error: V2AssetCatalogError) -> RecommendedCatalogStatusResponseV2:
        return RecommendedCatalogStatusResponseV2(
            status="invalid",
            last_error_code=error.code,
            message=error.message,
        )

    def index_package(
        self, candidate: CatalogPackageCandidate
    ) -> RecommendedCatalogStatusResponseV2:
        """Validate package files and atomically index metadata without copying media."""

        try:
            manifest, manifest_sha256 = self._load_package_manifest(candidate)
            licenses = self._load_licenses(candidate, manifest)
            if self._ready_identity_matches(manifest.catalog_version, manifest_sha256):
                return self._status_for_verified_manifest(manifest, manifest_sha256)
            verified = self._verify_declared_media(candidate.root, manifest, licenses)
            self._commit_verified_graph(manifest, licenses, verified, manifest_sha256)
            return self._status_for_verified_manifest(manifest, manifest_sha256)
        except V2AssetCatalogError as error:
            self._persist_invalid_candidate(candidate, error)
            return self.invalid_status(error)

    def _load_package_manifest(
        self, candidate: CatalogPackageCandidate
    ) -> tuple[CatalogManifestV1, str]:
        try:
            raw = candidate.manifest_path.read_bytes()
            manifest = CatalogManifestV1.model_validate_json(raw)
        except (OSError, ValidationError, ValueError) as error:
            raise V2AssetCatalogError(
                "recommended_catalog_manifest_invalid", "Catalog manifest is invalid."
            ) from error
        if manifest.catalog_version != candidate.catalog_version:
            raise V2AssetCatalogError(
                "recommended_catalog_manifest_invalid",
                "Catalog version directory does not match manifest.",
            )
        return manifest, hashlib.sha256(raw).hexdigest()

    def _load_licenses(
        self, candidate: CatalogPackageCandidate, manifest: CatalogManifestV1
    ) -> CatalogLicenseManifestV1:
        try:
            path = _safe_package_path(candidate.root, manifest.license_manifest_path)
            return CatalogLicenseManifestV1.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            raise V2AssetCatalogError(
                "recommended_catalog_manifest_invalid", "Catalog license manifest is invalid."
            ) from error

    def _verify_declared_media(
        self,
        root: Path,
        manifest: CatalogManifestV1,
        _licenses: CatalogLicenseManifestV1,
    ) -> dict[str, tuple[str, str]]:
        declared = {"catalog.json", manifest.license_manifest_path}
        verified: dict[str, tuple[str, str]] = {}
        for entity in manifest.entities:
            member = entity.members[0]
            for declaration in (member.original, member.preview):
                declared.add(declaration.path)
                path = _safe_package_path(root, declaration.path)
                _validate_file(
                    path,
                    declaration.sha256,
                    declaration.size_bytes,
                    declaration.mime_type,
                    declaration.width,
                    declaration.height,
                )
            verified[member.member_id] = (member.original.path, member.preview.path)
        _validate_declared_file_set(root, declared)
        return verified

    def _commit_verified_graph(
        self,
        manifest: CatalogManifestV1,
        licenses: CatalogLicenseManifestV1,
        verified: dict[str, tuple[str, str]],
        manifest_sha256: str,
    ) -> None:
        catalog_id = _catalog_id(manifest.catalog_version)
        now = _utc_now()
        license_entry = licenses.licenses[0]
        try:
            with self._repository.database.engine.begin() as connection:
                self._repository.upsert_catalog(
                    _catalog_record(
                        manifest,
                        manifest_sha256,
                        status="ready",
                        installed_at=now,
                    ),
                    connection=connection,
                )
                for entity in manifest.entities:
                    member = entity.members[0]
                    original_path, preview_path = verified[member.member_id]
                    self._repository.import_asset_version(
                        AssetRecordCreate(
                            asset_id=member.asset_id,
                            media_type="image",
                            source_type="recommended",
                            display_name=entity.display_name,
                        ),
                        AssetVersionCreate(
                            version_id=member.version_id,
                            asset_id=member.asset_id,
                            storage_key=_storage_key(manifest.catalog_version, original_path),
                            sha256=member.original.sha256,
                            size_bytes=member.original.size_bytes,
                            mime_type=member.original.mime_type,
                            width=member.original.width,
                            height=member.original.height,
                            metadata={
                                "catalog_id": catalog_id,
                                "license_id": license_entry.license_id,
                                "source_url": manifest.source_url,
                                "attribution": license_entry.attribution,
                                "preview_storage_key": _storage_key(
                                    manifest.catalog_version, preview_path
                                ),
                                "preview_sha256": member.preview.sha256,
                                "preview_mime_type": member.preview.mime_type,
                                "preview_size_bytes": member.preview.size_bytes,
                                "preview_width": member.preview.width,
                                "preview_height": member.preview.height,
                            },
                        ),
                        connection=connection,
                    )
                    try:
                        self._repository.get_entity(entity.entity_id, connection=connection)
                    except V2PersistenceError as error:
                        if error.code != "asset_library_entity_not_found":
                            raise
                        self._repository.create_entity(
                            AssetEntityCreate(
                                entity_id=entity.entity_id,
                                scope="recommended",
                                entity_type=entity.entity_type,
                                library_category=entity.library_category,
                                display_name=entity.display_name,
                                description=entity.description,
                                tags=entity.tags,
                                catalog_id=catalog_id,
                            ),
                            members=(
                                AssetEntityMemberCreate(
                                    member_id=member.member_id,
                                    asset_id=member.asset_id,
                                    version_id=member.version_id,
                                    semantic_type=member.semantic_type,
                                    is_primary=member.is_primary,
                                    is_default_reference=member.is_default_reference,
                                    sort_order=member.sort_order,
                                ),
                            ),
                            connection=connection,
                        )
        except V2PersistenceError as error:
            raise V2AssetCatalogError(
                "recommended_catalog_metadata_commit_failed",
                "Catalog metadata could not be indexed.",
            ) from error

    def _ready_identity_matches(self, catalog_version: str, manifest_sha256: str) -> bool:
        try:
            catalog = self._repository.get_catalog(_catalog_id(catalog_version))
        except V2PersistenceError as error:
            if error.code == "asset_catalog_not_found":
                return False
            raise V2AssetCatalogError(
                "recommended_catalog_metadata_commit_failed", "Catalog metadata is unavailable."
            ) from error
        return catalog.status == "ready" and catalog.manifest_sha256 == manifest_sha256

    def _status_for_verified_manifest(
        self, manifest: CatalogManifestV1, manifest_sha256: str
    ) -> RecommendedCatalogStatusResponseV2:
        return RecommendedCatalogStatusResponseV2(
            catalog_key=manifest.catalog_key,
            catalog_version=manifest.catalog_version,
            status="ready",
            entity_count=len(manifest.entities),
            member_count=len(manifest.entities),
            manifest_sha256=manifest_sha256,
            message="Recommended assets are ready.",
        )

    def _indexing_status(
        self, manifest: CatalogManifestV1, manifest_sha256: str
    ) -> RecommendedCatalogStatusResponseV2:
        return RecommendedCatalogStatusResponseV2(
            catalog_key=manifest.catalog_key,
            catalog_version=manifest.catalog_version,
            status="indexing",
            entity_count=len(manifest.entities),
            member_count=len(manifest.entities),
            manifest_sha256=manifest_sha256,
            message="Recommended assets are indexing.",
        )

    def _persist_invalid_candidate(
        self, candidate: CatalogPackageCandidate, error: V2AssetCatalogError
    ) -> None:
        try:
            self._repository.upsert_catalog(
                AssetCatalogRecordV2(
                    catalog_id=_catalog_id(candidate.catalog_version),
                    catalog_key="adcraft-recommended-assets-v1",
                    catalog_version=candidate.catalog_version,
                    source_type="recommended_local_catalog",
                    manifest_sha256="0" * 64,
                    archive_url="local://recommended-assets",
                    archive_sha256="0" * 64,
                    license_manifest={},
                    status="failed",
                    last_error_code=error.code,
                    last_error_message=error.message,
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
            )
        except V2PersistenceError:
            return


def _catalog_record(
    manifest: CatalogManifestV1,
    manifest_sha256: str,
    *,
    status: str,
    installed_at: str | None = None,
) -> AssetCatalogRecordV2:
    now = _utc_now()
    return AssetCatalogRecordV2(
        catalog_id=_catalog_id(manifest.catalog_version),
        catalog_key=manifest.catalog_key,
        catalog_version=manifest.catalog_version,
        source_type="recommended_local_catalog",
        manifest_sha256=manifest_sha256,
        archive_url=manifest.source_url or "local://recommended-assets",
        archive_sha256=manifest_sha256,
        license_manifest={},
        status=status,  # type: ignore[arg-type]
        is_current=True,
        progress_current=len(manifest.entities),
        progress_total=len(manifest.entities),
        installed_at=installed_at,
        created_at=now,
        updated_at=now,
    )


def _catalog_id(catalog_version: str) -> str:
    return f"catalog_recommended_{catalog_version.replace('.', '_')}"


def _storage_key(catalog_version: str, relative_path: str) -> str:
    return (
        Path("assets") / "catalogs" / "recommended" / f"v{catalog_version}" / relative_path
    ).as_posix()


def _safe_package_path(root: Path, relative_path: str) -> Path:
    if relative_path.startswith("/") or "\\" in relative_path:
        raise ValueError("catalog package path is unsafe")
    relative = Path(*relative_path.split("/"))
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("catalog package path is unsafe")
    target = root / relative
    root_resolved = root.resolve(strict=True)
    target_resolved = target.resolve(strict=False)
    if root_resolved not in (target_resolved, *target_resolved.parents):
        raise ValueError("catalog package path is unsafe")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("catalog package symlinks are not allowed")
    return target


def _validate_declared_file_set(root: Path, declared: set[str]) -> None:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise V2AssetCatalogError(
                "recommended_catalog_member_invalid", "Catalog package has an unsafe member."
            )
        if path.relative_to(root).as_posix() not in declared:
            raise V2AssetCatalogError(
                "recommended_catalog_member_invalid", "Catalog package has an undeclared member."
            )


def _validate_file(
    path: Path,
    expected_sha256: str,
    expected_size: int,
    expected_mime: str,
    expected_width: int,
    expected_height: int,
) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
        raise V2AssetCatalogError(
            "recommended_catalog_member_missing", "Catalog media member is unavailable."
        )
    if _sha256_file(path) != expected_sha256:
        raise V2AssetCatalogError(
            "recommended_catalog_member_invalid", "Catalog media member could not be verified."
        )
    mime, width, height = _image_metadata(path)
    if (mime, width, height) != (expected_mime, expected_width, expected_height):
        raise V2AssetCatalogError(
            "recommended_catalog_member_invalid", "Catalog media member metadata is invalid."
        )


def _image_metadata(path: Path) -> tuple[str, int, int]:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        return "image/png", int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        position = 2
        while position + 9 <= len(data):
            if data[position] != 0xFF:
                break
            marker = data[position + 1]
            position += 2
            if marker in {0xD8, 0xD9}:
                continue
            length = int.from_bytes(data[position : position + 2], "big")
            if length < 2 or position + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2}:
                return (
                    "image/jpeg",
                    int.from_bytes(data[position + 5 : position + 7], "big"),
                    int.from_bytes(data[position + 3 : position + 5], "big"),
                )
            position += length
    raise V2AssetCatalogError(
        "recommended_catalog_member_invalid", "Catalog media member metadata is invalid."
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
