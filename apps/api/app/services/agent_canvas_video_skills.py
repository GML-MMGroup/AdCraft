"""Validated, progressively disclosed Agent Canvas Video Skill packages."""

from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_video_skills import (
    VideoSkillPublicDetailV2,
    VideoSkillPreviewV2,
    VideoSkillSummaryListV2,
)


_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "agent" / "video-skills"
_REQUIRED_PACKAGE_FILES = {"SKILL.md", "recipe.json"}


class VideoSkillManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str = Field(default="commercial", min_length=1)
    tags: tuple[str, ...] = ()
    supported_use_cases: tuple[str, ...] = ()
    preview: VideoSkillPreviewV2 | None = None
    files: dict[str, str]
    allowed_hooks: tuple[str, ...] = ()
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class LoadedVideoSkillV2:
    manifest: VideoSkillManifestV2
    instructions: str
    recipe: dict[str, Any]
    prompt_fragments: dict[str, str]
    package_digest: str


class VideoSkillRegistry:
    """Load only declared files from digest-verified Video Skill packages."""

    def __init__(self, root: Path = _DEFAULT_ROOT) -> None:
        self._root = root

    def list_public_skills(self) -> tuple[VideoSkillManifestV2, ...]:
        manifests = []
        if not self._root.is_dir():
            return ()
        for manifest_path in sorted(self._root.glob("*/*/manifest.json")):
            manifests.append(
                self._read_manifest(manifest_path).model_copy(update={"instructions": None})
            )
        return tuple(manifests)

    def list_public_catalog(
        self,
        *,
        category: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> VideoSkillSummaryListV2:
        if not 1 <= limit <= 100:
            raise _skill_error("skill_catalog_page_invalid", "Skill page is invalid.")
        manifests = [
            manifest
            for manifest in self.list_public_skills()
            if category is None or manifest.category == category
        ]
        start = _decode_cursor(cursor) if cursor else 0
        if start > len(manifests):
            raise _skill_error("skill_catalog_cursor_invalid", "Skill cursor is invalid.")
        page = manifests[start : start + limit]
        next_offset = start + len(page)
        return VideoSkillSummaryListV2(
            items=tuple(_public_detail(manifest) for manifest in page),
            next_cursor=(_encode_cursor(next_offset) if next_offset < len(manifests) else None),
        )

    def get_public_detail(self, skill_id: str) -> VideoSkillPublicDetailV2:
        matches = [
            manifest for manifest in self.list_public_skills() if manifest.skill_id == skill_id
        ]
        if not matches:
            raise _skill_error("skill_not_found", "Video Skill was not found.")
        manifest = max(matches, key=lambda item: item.version)
        return _public_detail(manifest)

    def load(self, skill_id: str, version: str) -> LoadedVideoSkillV2:
        package = (self._root / skill_id / version).resolve()
        if self._root.resolve() not in package.parents:
            raise _skill_error("video_skill_not_found", "Video Skill was not found.")
        manifest = self._read_manifest(package / "manifest.json")
        if manifest.skill_id != skill_id or manifest.version != version:
            raise _skill_error("video_skill_not_found", "Video Skill identity is invalid.")
        if not _REQUIRED_PACKAGE_FILES.issubset(manifest.files) or any(
            not _allowed_package_path(path) for path in manifest.files
        ):
            raise _skill_error("agent_skill_manifest_invalid", "Video Skill files are invalid.")
        verified: dict[str, bytes] = {}
        for relative_path, expected_digest in manifest.files.items():
            path = (package / relative_path).resolve()
            if package not in path.parents:
                raise _skill_error("agent_skill_manifest_invalid", "Video Skill path is invalid.")
            try:
                content = path.read_bytes()
            except OSError as error:
                raise _skill_error(
                    "agent_skill_file_missing",
                    "A declared Video Skill file is missing.",
                ) from error
            canonical_content = _canonical_content(relative_path, content)
            if hashlib.sha256(canonical_content).hexdigest() != expected_digest:
                raise _skill_error(
                    "agent_skill_digest_mismatch",
                    "Video Skill file digest does not match its manifest.",
                )
            verified[relative_path] = canonical_content
        try:
            recipe = json.loads(verified["recipe.json"])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _skill_error(
                "agent_skill_manifest_invalid",
                "Video Skill recipe is invalid.",
            ) from error
        if not isinstance(recipe, dict):
            raise _skill_error("agent_skill_manifest_invalid", "Video Skill recipe is invalid.")
        return LoadedVideoSkillV2(
            manifest=manifest,
            instructions=verified["SKILL.md"].decode("utf-8"),
            recipe=recipe,
            prompt_fragments={},
            package_digest=_package_digest(manifest, verified),
        )

    @staticmethod
    def _read_manifest(path: Path) -> VideoSkillManifestV2:
        try:
            return VideoSkillManifestV2.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise _skill_error(
                "agent_skill_manifest_invalid",
                "Video Skill manifest is invalid.",
            ) from error


def _skill_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="video_skill_registry")


def _allowed_package_path(path: str) -> bool:
    return (
        path in _REQUIRED_PACKAGE_FILES
        or path.startswith("prompts/")
        or path.startswith("previews/")
        or path == "agent-hooks.ts"
    ) and ".." not in Path(path).parts


def _canonical_content(relative_path: str, content: bytes) -> bytes:
    if Path(relative_path).suffix.casefold() not in {".json", ".md", ".ts"}:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _skill_error(
            "agent_skill_manifest_invalid",
            "Video Skill text encoding is invalid.",
        ) from error
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return f"{normalized}\n".encode("utf-8")


def _package_digest(
    manifest: VideoSkillManifestV2,
    verified: dict[str, bytes],
) -> str:
    digest = hashlib.sha256()
    digest.update(f"{manifest.skill_id}\n{manifest.version}\n".encode())
    for relative_path in sorted(verified):
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(verified[relative_path]).digest())
    return digest.hexdigest()


def _public_detail(manifest: VideoSkillManifestV2) -> VideoSkillPublicDetailV2:
    return VideoSkillPublicDetailV2(
        skill_id=manifest.skill_id,
        version=manifest.version,
        title=manifest.display_name,
        summary=manifest.description,
        category=manifest.category,
        tags=manifest.tags,
        supported_use_cases=manifest.supported_use_cases,
        preview=manifest.preview,
    )


def _encode_cursor(offset: int) -> str:
    return urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        offset = int(urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError) as error:
        raise _skill_error("skill_catalog_cursor_invalid", "Skill cursor is invalid.") from error
    if offset < 0:
        raise _skill_error("skill_catalog_cursor_invalid", "Skill cursor is invalid.")
    return offset
