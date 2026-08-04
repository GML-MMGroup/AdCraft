"""Validate published Video Style Skill packages without external services."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from app.persistence.errors import V2PersistenceError
from app.services.agent_canvas_video_skills import VideoSkillRegistry
from app.services.video_style_skill_curation import (
    CuratedSkillMapV1,
    EXPECTED_CURATED_SKILL_IDS,
    load_curation_map,
    validate_source_lineage,
)


_FIXED_RUNTIME_POLICY = (
    re.compile(r"\b(?:duration|frame rate|bpm)\s*[:=]\s*\d", re.IGNORECASE),
    re.compile(r"\b(?:model|provider)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b(?:9:16|16:9|1:1|4:3|3:4)\b"),
    re.compile(r"\b\d{3,4}x\d{3,4}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:must|always)\s+(?:use|call|run)\s+(?:the\s+)?(?:model|provider|tool)\b",
        re.IGNORECASE,
    ),
)
_NAMED_IMITATION = re.compile(
    r"\b(?:imitate|copy|replicate|in the style of|inspired by)\s+(?:director|artist|brand|franchise|character|show)?\s*[A-Z][A-Za-z]+",
    re.IGNORECASE,
)


def validate_video_style_skills(root: Path, *, source_root: Path | None = None) -> int:
    """Validate every catalog entry and return the published package count."""

    registry = VideoSkillRegistry(root)
    seen: set[tuple[str, str]] = set()
    curated_ids: list[str] = []
    loaded_by_id = {}
    for entry in registry.published_entries():
        identity = (entry.skill_id, entry.version)
        if identity in seen:
            raise _error("video_skill_catalog_invalid", "Catalog identities are not unique.")
        seen.add(identity)
        loaded = registry.load(entry.skill_id, entry.version)
        loaded_by_id[entry.skill_id] = loaded
        if entry.skill_id != "platform-default":
            curated_ids.append(entry.skill_id)
        values = (
            loaded.manifest.display_name,
            loaded.manifest.description,
            *loaded.manifest.tags,
            *loaded.manifest.supported_use_cases,
            loaded.global_guidance,
            *(guidance.text for guidance in loaded.role_guidance.values()),
        )
        if any(not value.isascii() for value in values):
            raise _error(
                "curated_skill_non_english",
                f"Published metadata and guidance must be English: {entry.skill_id}.",
            )
        for value in values:
            if any(pattern.search(value) for pattern in _FIXED_RUNTIME_POLICY):
                raise _error(
                    "curated_skill_runtime_instruction",
                    f"Published guidance contains runtime policy: {entry.skill_id}.",
                )
            if _NAMED_IMITATION.search(value):
                raise _error(
                    "curated_skill_named_imitation",
                    f"Published guidance contains named imitation: {entry.skill_id}.",
                )
        role_bodies = [
            " ".join(item.text.split()).casefold() for item in loaded.role_guidance.values()
        ]
        if len(role_bodies) != len(set(role_bodies)):
            raise _error(
                "curated_skill_role_duplication",
                f"Role guidance must be distinct: {entry.skill_id}.",
            )
    if tuple(curated_ids) != EXPECTED_CURATED_SKILL_IDS:
        raise _error(
            "curation_catalog_mismatch",
            "The published curated catalog does not match the approved identity order.",
        )
    curation_path = root / "curation-map.json"
    curated_entries = {identity for identity in seen if identity[0] != "platform-default"}
    if curation_path.exists():
        curation = load_curation_map(curation_path)
        curated_records = {(record.skill_id, record.version) for record in curation.skills}
        if curated_records != curated_entries:
            raise _error(
                "curation_catalog_mismatch",
                "The curation map does not match the published curated catalog.",
            )
        _validate_curation_evidence(curation)
        _validate_differentiation(curation, loaded_by_id)
        if source_root is not None:
            diagnostics = validate_source_lineage(curation, source_root)
            if diagnostics:
                first = diagnostics[0]
                raise _error(first.code, f"{first.skill_id}: {first.detail}")
    elif curated_entries:
        raise _error("curation_catalog_mismatch", "The curation map is missing.")
    return len(seen)


def _validate_curation_evidence(curation: CuratedSkillMapV1) -> None:
    generic = {"cleaned up", "adapted", "translated", "removed constraints"}
    for record in curation.skills:
        descriptions = (
            *record.removed_runtime_constraints,
            record.naming_adaptation,
            record.commercial_adaptation,
        )
        evidence = (*record.retained_methods, *descriptions)
        if any(not item.isascii() or not item.strip() for item in evidence) or any(
            len(item.strip()) < 8 for item in descriptions
        ):
            raise _error(
                "curation_evidence_incomplete",
                f"Curation evidence must be concrete English text: {record.skill_id}.",
            )
        if any(item.strip().casefold() in generic for item in evidence):
            raise _error(
                "curation_evidence_incomplete",
                f"Curation evidence is too generic: {record.skill_id}.",
            )


def _validate_differentiation(curation: CuratedSkillMapV1, loaded_by_id: dict) -> None:
    for record in curation.skills:
        loaded = loaded_by_id.get(record.skill_id)
        if loaded is None:
            continue
        body = loaded.global_guidance.casefold()
        matched = sum(method.casefold() in body for method in record.retained_methods)
        if matched < min(2, len(record.retained_methods)):
            raise _error(
                "curated_skill_not_differentiated",
                f"Published guidance lacks retained creative methods: {record.skill_id}.",
            )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="video_style_skill_validator")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("agent/video-skills"))
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    count = validate_video_style_skills(args.root, source_root=args.source_root)
    print(f"Validated {count} published Video Style Skill package(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
