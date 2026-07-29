"""Validated, progressively disclosed Agent Canvas Video Skill packages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.persistence.errors import V2PersistenceError


_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "agent" / "video-skills"
_REQUIRED_PACKAGE_FILES = {"SKILL.md", "recipe.json"}


class VideoSkillManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    files: dict[str, str]
    allowed_hooks: tuple[str, ...] = ()
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class LoadedVideoSkillV2:
    manifest: VideoSkillManifestV2
    instructions: str
    recipe: dict[str, Any]
    prompt_fragments: dict[str, str]


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
            if hashlib.sha256(content).hexdigest() != expected_digest:
                raise _skill_error(
                    "agent_skill_digest_mismatch",
                    "Video Skill file digest does not match its manifest.",
                )
            verified[relative_path] = content
        try:
            recipe = json.loads(verified["recipe.json"])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _skill_error(
                "agent_skill_manifest_invalid",
                "Video Skill recipe is invalid.",
            ) from error
        if not isinstance(recipe, dict) or not isinstance(recipe.get("planning_topics"), list):
            raise _skill_error("agent_skill_manifest_invalid", "Video Skill recipe is invalid.")
        return LoadedVideoSkillV2(
            manifest=manifest,
            instructions=verified["SKILL.md"].decode("utf-8"),
            recipe=recipe,
            prompt_fragments={},
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
