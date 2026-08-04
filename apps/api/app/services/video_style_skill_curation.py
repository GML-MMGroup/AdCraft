"""Deterministic maintainer checks for curated Video Style Skill packages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_GROUP_ID = re.compile(r"^[a-z0-9-]+-([0-9a-f]{8})$")
_FILE_SUFFIX = re.compile(r"^[0-9a-f]{8}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_CURATED_SKILL_IDS = (
    "new-product-tvc-campaign",
    "industrial-product-commercial",
    "product-promotional-film",
    "brand-manifesto-film",
    "one-take-commercial",
    "beat-synced-camera-commercial",
    "fashion-showcase-film",
    "jewelry-editorial-film",
    "luxury-silk-illustration",
    "art-deco-golden-age-romance",
    "theatrical-revue-glamour",
    "symmetrical-storybook-cinema",
    "controlled-psychological-thriller",
    "poetic-contemplative-cinema",
    "monumental-minimalist-science-fiction",
    "lived-in-epic-cinema",
    "geometric-suspense-cinema",
    "kinetic-wuxia-fantasy",
    "designer-toy-ip-film",
    "soft-3d-comfort-animation",
    "luminous-youth-anime",
    "dream-reality-psychological-anime",
    "kinetic-expressionist-animation",
    "chinese-traditional-art-animation",
    "retro-pixel-arcade",
    "retro-magical-girl-animation",
    "mixed-media-collage-motion",
    "surreal-pop-concept-film",
    "brand-mark-in-context",
    "chinese-millennium-dreamcore",
    "miniature-world-cinema",
    "hand-drawn-travel-journal",
    "gentle-everyday-vlog",
    "cinematic-food-story",
    "observational-human-documentary",
    "craft-process-film",
)


class _CurationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CuratedSourceV1(_CurationModel):
    group_id: str = Field(min_length=10)
    file_suffix: str = Field(min_length=8, max_length=8)
    source_title_en: str = Field(min_length=3)
    source_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_locator(self) -> "CuratedSourceV1":
        if not _GROUP_ID.fullmatch(self.group_id):
            raise ValueError("source group_id must end in an eight-character lowercase digest")
        if not _FILE_SUFFIX.fullmatch(self.file_suffix):
            raise ValueError("source file_suffix must be an eight-character lowercase digest")
        if not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        return self


class CuratedSkillRecordV1(_CurationModel):
    skill_id: str = Field(min_length=1)
    version: Literal["1.0.0"]
    sources: tuple[CuratedSourceV1, ...] = Field(min_length=1)
    retained_methods: tuple[str, ...] = Field(min_length=1)
    merged_duplicates: tuple[str, ...]
    removed_runtime_constraints: tuple[str, ...] = Field(min_length=1)
    naming_adaptation: str = Field(min_length=12)
    commercial_adaptation: str = Field(min_length=12)
    review_status: Literal["approved"]


class CuratedSkillMapV1(_CurationModel):
    curation_version: Literal["1"]
    skills: tuple[CuratedSkillRecordV1, ...]

    @model_validator(mode="after")
    def validate_unique_skills(self) -> "CuratedSkillMapV1":
        identities = [(record.skill_id, record.version) for record in self.skills]
        if len(identities) != len(set(identities)):
            raise ValueError("curation skill identities must be unique")
        return self


@dataclass(frozen=True, slots=True)
class CurationDiagnosticV1:
    code: str
    skill_id: str
    detail: str


class CurationSourceResolutionError(ValueError):
    """Stable source-locator failure used by the maintainer audit."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def load_curation_map(path: Path) -> CuratedSkillMapV1:
    """Load the private curation map with strict schema validation."""

    return CuratedSkillMapV1.model_validate_json(path.read_bytes())


def resolve_source(source_root: Path, group_id: str, file_suffix: str) -> Path:
    """Resolve one source by stable group and file suffixes."""

    group_match = _GROUP_ID.fullmatch(group_id)
    if group_match is None or _FILE_SUFFIX.fullmatch(file_suffix) is None:
        raise CurationSourceResolutionError(
            "curation_source_missing", "invalid curated source locator"
        )
    group_suffix = group_match.group(1)
    groups = [
        path
        for path in source_root.iterdir()
        if path.is_dir() and path.name.casefold().endswith(f"-{group_suffix}")
    ]
    if len(groups) != 1:
        code = "curation_source_missing" if not groups else "curation_source_ambiguous"
        raise CurationSourceResolutionError(
            code, f"expected one source group for {group_id}, found {len(groups)}"
        )
    matches = [path for path in groups[0].rglob(f"*-{file_suffix}.md") if path.is_file()]
    if len(matches) != 1:
        code = "curation_source_missing" if not matches else "curation_source_ambiguous"
        raise CurationSourceResolutionError(
            code,
            f"expected one source document for {group_id}:{file_suffix}, found {len(matches)}",
        )
    return matches[0]


def validate_source_lineage(
    curation: CuratedSkillMapV1,
    source_root: Path,
) -> tuple[CurationDiagnosticV1, ...]:
    """Verify optional maintainer source existence and frozen digests."""

    diagnostics: list[CurationDiagnosticV1] = []
    for record in curation.skills:
        for source in record.sources:
            try:
                path = resolve_source(source_root, source.group_id, source.file_suffix)
            except CurationSourceResolutionError as error:
                diagnostics.append(
                    CurationDiagnosticV1(
                        code=error.code,
                        skill_id=record.skill_id,
                        detail=str(error),
                    )
                )
                continue
            except OSError as error:
                diagnostics.append(
                    CurationDiagnosticV1(
                        code="curation_source_missing",
                        skill_id=record.skill_id,
                        detail=str(error),
                    )
                )
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != source.source_sha256:
                diagnostics.append(
                    CurationDiagnosticV1(
                        code="curation_source_digest_mismatch",
                        skill_id=record.skill_id,
                        detail=f"Digest mismatch for {source.group_id}:{source.file_suffix}.",
                    )
                )
    return tuple(diagnostics)
