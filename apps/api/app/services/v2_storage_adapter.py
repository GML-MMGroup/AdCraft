"""Content-addressed local media storage for the V2 asset-library boundary."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

from app.persistence.errors import V2PersistenceError
from app.services.v2_data_boundary import (
    V2DataBoundaryError,
    validate_v2_data_path,
    validate_v2_relative_path,
)


class StorageAdapter:
    """Publish verified media bytes under a data-root-relative content key."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def publish_verified_file(self, staging_path: Path, sha256: str, extension: str) -> str:
        """Verify and atomically publish a staging file, reusing valid content only."""

        expected_sha256 = _validated_sha256(sha256)
        source = staging_path.resolve(strict=False)
        if not source.is_file() or _sha256(source) != expected_sha256:
            raise _storage_error(
                "v2_storage_content_invalid", "Storage content could not be verified."
            )
        normalized_extension = _normalized_extension(extension)
        storage_key = _storage_key(expected_sha256, normalized_extension)
        target = self.resolve_local_path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.content_exists(storage_key, expected_sha256):
            source.unlink(missing_ok=True)
            return storage_key

        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temporary)
            _fsync_file(temporary)
            if _sha256(temporary) != expected_sha256:
                raise _storage_error(
                    "v2_storage_content_invalid", "Storage content could not be verified."
                )
            os.replace(temporary, target)
            source.unlink(missing_ok=True)
        except V2PersistenceError:
            raise
        except OSError as error:
            raise _storage_error(
                "v2_storage_publish_failed", "Storage content could not be published."
            ) from error
        finally:
            temporary.unlink(missing_ok=True)
        return storage_key

    def resolve_local_path(self, storage_key: str) -> Path:
        """Resolve one local object key without accepting arbitrary filesystem paths."""

        try:
            relative_path = validate_v2_relative_path(
                storage_key, operation="v2-storage-resolve-local-path"
            )
        except V2DataBoundaryError as error:
            raise _storage_error("v2_storage_key_invalid", "Storage key is invalid.") from error
        readable_prefixes = (
            ("assets", "objects", "sha256"),
            ("assets", "catalogs", "recommended"),
        )
        if not any(
            tuple(relative_path.parts[: len(prefix)]) == prefix for prefix in readable_prefixes
        ):
            raise _storage_error("v2_storage_key_invalid", "Storage key is invalid.")
        try:
            return validate_v2_data_path(
                self._data_dir,
                relative_path,
                operation="v2-storage-resolve-local-path",
            )
        except V2DataBoundaryError as error:
            raise _storage_error("v2_storage_key_invalid", "Storage key is invalid.") from error

    def content_exists(self, storage_key: str, sha256: str) -> bool:
        """Return whether a local object exists and still matches its expected hash."""

        try:
            expected_sha256 = _validated_sha256(sha256)
            path = self.resolve_local_path(storage_key)
        except V2PersistenceError:
            return False
        return path.is_file() and _sha256(path) == expected_sha256

    def file_exists(self, storage_key: str) -> bool:
        """Return cheap read readiness for approved regular non-symlink media files."""

        try:
            path = self.resolve_local_path(storage_key)
        except V2PersistenceError:
            return False
        return path.is_file() and not path.is_symlink()


def _storage_key(sha256: str, extension: str) -> str:
    return (
        Path("assets") / "objects" / "sha256" / sha256[:2] / sha256[2:4] / f"{sha256}.{extension}"
    ).as_posix()


def _validated_sha256(value: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise _storage_error("v2_storage_hash_invalid", "Storage hash is invalid.")
    return normalized


def _normalized_extension(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    if not normalized or len(normalized) > 16 or not normalized.isalnum():
        raise _storage_error("v2_storage_extension_invalid", "Storage extension is invalid.")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as source:
        os.fsync(source.fileno())


def _storage_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="storage_adapter")
