"""Validated, progressively disclosed Agent Canvas Video Style Skill packages."""

from __future__ import annotations

import hashlib
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_video_skills import (
    VideoSkillCatalogResponseV2,
    VideoSkillCategoryV2,
    VideoSkillPreviewV2,
    VideoSkillPublicDetailV2,
)


_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "agent" / "video-skills"
_SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_GLOBAL_GUIDANCE_BYTES = 4_096
_ROLE_GUIDANCE_BYTES = 4_096
_RESOLVED_CONTEXT_BYTES = 8_192
_SUPPORTED_ROLES = {
    "world_setting",
    "script",
    "product",
    "prop",
    "character",
    "scene",
    "storyboard",
    "video",
    "bgm",
    "quick_media",
}


class VideoSkillCatalogEntryV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_order: int = Field(ge=0)

    @field_validator("version")
    @classmethod
    def validate_semantic_version(cls, value: str) -> str:
        if not _SEMANTIC_VERSION.fullmatch(value):
            raise ValueError("Style Skill versions must use semantic versioning.")
        return value


class VideoSkillCatalogFileV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str = Field(min_length=1)
    categories: tuple[VideoSkillCategoryV2, ...]
    skills: tuple[VideoSkillCatalogEntryV2, ...]


class VideoSkillManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str = Field(min_length=1)
    tags: tuple[str, ...] = ()
    supported_use_cases: tuple[str, ...] = ()
    preview: VideoSkillPreviewV2 | None = None
    display_order: int = Field(ge=0)
    files: dict[str, str]
    role_guidance: dict[str, str] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def validate_semantic_version(cls, value: str) -> str:
        if not _SEMANTIC_VERSION.fullmatch(value):
            raise ValueError("Style Skill versions must use semantic versioning.")
        return value


@dataclass(frozen=True, slots=True)
class LoadedRoleGuidanceV2:
    role: str
    path: str
    text: str
    digest: str


@dataclass(frozen=True, slots=True)
class LoadedVideoStyleSkillV2:
    manifest: VideoSkillManifestV2
    global_guidance: str
    role_guidance: dict[str, LoadedRoleGuidanceV2]
    package_digest: str


@dataclass(frozen=True, slots=True)
class LoadedVideoSkillCatalogV2:
    catalog_version: str
    categories: tuple[VideoSkillCategoryV2, ...]
    items: tuple[VideoSkillPublicDetailV2, ...]


@dataclass(frozen=True, slots=True)
class VideoSkillDiagnosticV2:
    skill_id: str
    version: str
    code: str


class VideoSkillRegistry:
    """Load only explicitly published, digest-verified content packages."""

    def __init__(self, root: Path = _DEFAULT_ROOT) -> None:
        self._root = root
        self._diagnostics: tuple[VideoSkillDiagnosticV2, ...] = ()

    @property
    def diagnostics(self) -> tuple[VideoSkillDiagnosticV2, ...]:
        return self._diagnostics

    def validate_startup(self) -> None:
        try:
            catalog = self.load_catalog()
        except V2PersistenceError as error:
            if error.code == "video_skill_catalog_invalid":
                raise
            raise _skill_error(
                "video_skill_catalog_invalid",
                "The Video Style Skill catalog is invalid.",
            ) from error
        if not any(item.skill_id == "platform-default" for item in catalog.items):
            raise _skill_error(
                "video_skill_catalog_invalid",
                "The required Platform Default Style Skill is invalid.",
            )

    def load_catalog(self) -> LoadedVideoSkillCatalogV2:
        catalog = self._read_catalog()
        categories = _ordered_categories(catalog.categories)
        category_ids = {category.category_id for category in categories}
        if len(category_ids) != len(categories):
            raise _skill_error(
                "video_skill_catalog_invalid", "Video Style Skill categories are invalid."
            )
        entries = sorted(catalog.skills, key=lambda item: (item.display_order, item.skill_id))
        identities = {(entry.skill_id, entry.version) for entry in entries}
        if len(identities) != len(entries) or len({entry.skill_id for entry in entries}) != len(
            entries
        ):
            raise _skill_error(
                "video_skill_catalog_invalid", "Video Style Skill entries are not unique."
            )
        items: list[VideoSkillPublicDetailV2] = []
        diagnostics: list[VideoSkillDiagnosticV2] = []
        for entry in entries:
            try:
                loaded = self._load_published_entry(entry)
                if loaded.manifest.category not in category_ids:
                    raise _skill_error(
                        "agent_skill_manifest_invalid",
                        "Video Style Skill category is not published.",
                    )
                if loaded.manifest.display_order != entry.display_order:
                    raise _skill_error(
                        "agent_skill_manifest_invalid",
                        "Video Style Skill display order does not match the catalog.",
                    )
            except V2PersistenceError as error:
                if entry.skill_id == "platform-default":
                    raise _skill_error(
                        "video_skill_catalog_invalid",
                        "The required Platform Default Style Skill is invalid.",
                    ) from error
                diagnostics.append(
                    VideoSkillDiagnosticV2(
                        skill_id=entry.skill_id,
                        version=entry.version,
                        code=error.code,
                    )
                )
                continue
            items.append(_public_detail(loaded.manifest))
        self._diagnostics = tuple(diagnostics)
        return LoadedVideoSkillCatalogV2(
            catalog_version=catalog.catalog_version,
            categories=categories,
            items=tuple(items),
        )

    def published_entries(self) -> tuple[VideoSkillCatalogEntryV2, ...]:
        """Return the validated publication identities in deterministic order."""

        return tuple(
            sorted(
                self._read_catalog().skills,
                key=lambda item: (item.display_order, item.skill_id),
            )
        )

    def list_public_skills(self) -> tuple[VideoSkillManifestV2, ...]:
        catalog = self._read_catalog()
        valid_ids = {item.skill_id for item in self.load_catalog().items}
        return tuple(
            self._load_published_entry(entry).manifest
            for entry in sorted(
                catalog.skills,
                key=lambda item: (item.display_order, item.skill_id),
            )
            if entry.skill_id in valid_ids
        )

    def list_public_catalog(
        self,
        *,
        category: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> VideoSkillCatalogResponseV2:
        if not 1 <= limit <= 100:
            raise _skill_error("skill_catalog_page_invalid", "Skill page is invalid.")
        catalog = self.load_catalog()
        items = [item for item in catalog.items if category is None or item.category == category]
        start = _decode_cursor(cursor) if cursor else 0
        if start > len(items):
            raise _skill_error("skill_catalog_cursor_invalid", "Skill cursor is invalid.")
        page = items[start : start + limit]
        next_offset = start + len(page)
        return VideoSkillCatalogResponseV2(
            catalog_version=catalog.catalog_version,
            categories=catalog.categories,
            items=tuple(page),
            next_cursor=(_encode_cursor(next_offset) if next_offset < len(items) else None),
        )

    def get_public_detail(self, skill_id: str) -> VideoSkillPublicDetailV2:
        match = next(
            (item for item in self.load_catalog().items if item.skill_id == skill_id),
            None,
        )
        if match is None:
            raise _skill_error("video_skill_not_found", "Video Style Skill was not found.")
        return match

    def load(self, skill_id: str, version: str) -> LoadedVideoStyleSkillV2:
        entry = next(
            (
                item
                for item in self._read_catalog().skills
                if item.skill_id == skill_id and item.version == version
            ),
            None,
        )
        if entry is None:
            raise _skill_error("video_skill_not_found", "Video Style Skill was not found.")
        return self._load_published_entry(entry)

    def _load_published_entry(self, entry: VideoSkillCatalogEntryV2) -> LoadedVideoStyleSkillV2:
        package = (self._root / entry.skill_id / entry.version).resolve()
        if self._root.resolve() not in package.parents:
            raise _skill_error("video_skill_not_found", "Video Style Skill was not found.")
        manifest = self._read_manifest(package / "manifest.json")
        if (
            manifest.skill_id != entry.skill_id
            or manifest.version != entry.version
            or manifest.display_order != entry.display_order
        ):
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill identity is invalid."
            )
        if "SKILL.md" not in manifest.files:
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill files are invalid."
            )
        if set(manifest.role_guidance) - _SUPPORTED_ROLES:
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill role mapping is invalid."
            )
        if set(manifest.role_guidance.values()) - set(manifest.files):
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill role mapping is invalid."
            )
        if any(not _allowed_package_path(path) for path in manifest.files):
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill files are invalid."
            )
        verified: dict[str, bytes] = {}
        for relative_path, expected_digest in manifest.files.items():
            path = (package / relative_path).resolve()
            if package not in path.parents:
                raise _skill_error(
                    "agent_skill_manifest_invalid", "Video Style Skill path is invalid."
                )
            try:
                content = path.read_bytes()
            except OSError as error:
                raise _skill_error(
                    "agent_skill_manifest_invalid",
                    "A declared Video Style Skill file is missing.",
                ) from error
            canonical = _canonical_text(relative_path, content)
            if hashlib.sha256(canonical).hexdigest() != expected_digest:
                raise _skill_error(
                    "agent_skill_digest_mismatch",
                    "Video Style Skill file digest does not match its manifest.",
                )
            verified[relative_path] = canonical
        _reject_undeclared_files(package, set(manifest.files))
        name, description, global_guidance = _parse_skill_markdown(verified["SKILL.md"])
        if _normalize_metadata(name) != _normalize_metadata(
            manifest.display_name
        ) or _normalize_metadata(description) != _normalize_metadata(manifest.description):
            raise _skill_error(
                "agent_skill_manifest_invalid",
                "Video Style Skill frontmatter does not match its manifest.",
            )
        _check_budget(global_guidance, _GLOBAL_GUIDANCE_BYTES)
        roles: dict[str, LoadedRoleGuidanceV2] = {}
        for role, relative_path in manifest.role_guidance.items():
            text = verified[relative_path].decode("utf-8")
            _check_budget(text, _ROLE_GUIDANCE_BYTES)
            if len(global_guidance.encode("utf-8")) + len(text.encode("utf-8")) > (
                _RESOLVED_CONTEXT_BYTES
            ):
                raise _skill_error(
                    "style_skill_context_budget_exceeded",
                    "Video Style Skill context exceeds its byte budget.",
                )
            roles[role] = LoadedRoleGuidanceV2(
                role=role,
                path=relative_path,
                text=text,
                digest=manifest.files[relative_path],
            )
        return LoadedVideoStyleSkillV2(
            manifest=manifest,
            global_guidance=global_guidance,
            role_guidance=roles,
            package_digest=_package_digest(manifest, verified),
        )

    def _read_catalog(self) -> VideoSkillCatalogFileV2:
        try:
            return VideoSkillCatalogFileV2.model_validate_json(
                (self._root / "catalog.json").read_bytes()
            )
        except (OSError, ValueError) as error:
            raise _skill_error(
                "video_skill_catalog_invalid", "Video Style Skill catalog is invalid."
            ) from error

    @staticmethod
    def _read_manifest(path: Path) -> VideoSkillManifestV2:
        try:
            return VideoSkillManifestV2.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill manifest is invalid."
            ) from error


def _ordered_categories(
    categories: tuple[VideoSkillCategoryV2, ...],
) -> tuple[VideoSkillCategoryV2, ...]:
    return tuple(sorted(categories, key=lambda item: (item.display_order, item.category_id)))


def _skill_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="video_skill_registry")


def _allowed_package_path(path: str) -> bool:
    parts = Path(path).parts
    if ".." in parts or Path(path).is_absolute():
        return False
    return (
        path == "SKILL.md"
        or (path.startswith("references/") and Path(path).suffix.casefold() == ".md")
        or path.startswith("previews/")
    )


def _canonical_text(relative_path: str, content: bytes) -> bytes:
    if relative_path.startswith("previews/") and Path(relative_path).suffix.casefold() not in {
        ".md",
        ".txt",
        ".json",
    }:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _skill_error(
            "agent_skill_manifest_invalid", "Video Style Skill text encoding is invalid."
        ) from error
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return f"{normalized}\n".encode("utf-8")


def _reject_undeclared_files(package: Path, declared: set[str]) -> None:
    actual = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != declared:
        raise _skill_error(
            "agent_skill_manifest_invalid",
            "Video Style Skill package contains undeclared files.",
        )


def _parse_skill_markdown(content: bytes) -> tuple[str, str, str]:
    text = content.decode("utf-8")
    if not text.startswith("---\n"):
        raise _skill_error(
            "agent_skill_manifest_invalid", "Video Style Skill frontmatter is missing."
        )
    try:
        frontmatter, body = text[4:].split("\n---\n", 1)
    except ValueError as error:
        raise _skill_error(
            "agent_skill_manifest_invalid", "Video Style Skill frontmatter is invalid."
        ) from error
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            raise _skill_error(
                "agent_skill_manifest_invalid", "Video Style Skill frontmatter is invalid."
            )
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    if set(values) != {"name", "description"} or not all(values.values()):
        raise _skill_error(
            "agent_skill_manifest_invalid", "Video Style Skill frontmatter is invalid."
        )
    guidance = body.lstrip("\n")
    if not guidance.strip():
        raise _skill_error("agent_skill_manifest_invalid", "Video Style Skill guidance is empty.")
    return values["name"], values["description"], guidance


def _normalize_metadata(value: str) -> str:
    return " ".join(value.split())


def _check_budget(text: str, limit: int) -> None:
    if len(text.encode("utf-8")) > limit:
        raise _skill_error(
            "style_skill_context_budget_exceeded",
            "Video Style Skill context exceeds its byte budget.",
        )


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
        display_order=manifest.display_order,
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
