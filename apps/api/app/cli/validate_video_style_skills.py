"""Validate published Video Style Skill packages without external services."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from app.persistence.errors import V2PersistenceError
from app.services.agent_canvas_video_skills import VideoSkillRegistry


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


def validate_video_style_skills(root: Path) -> int:
    """Validate every catalog entry and return the published package count."""

    registry = VideoSkillRegistry(root)
    seen: set[tuple[str, str]] = set()
    for entry in registry.published_entries():
        identity = (entry.skill_id, entry.version)
        if identity in seen:
            raise _error("video_skill_catalog_invalid", "Catalog identities are not unique.")
        seen.add(identity)
        loaded = registry.load(entry.skill_id, entry.version)
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
                "agent_skill_manifest_invalid",
                f"Published metadata and guidance must be English: {entry.skill_id}.",
            )
        for value in values:
            if any(pattern.search(value) for pattern in _FIXED_RUNTIME_POLICY):
                raise _error(
                    "agent_skill_manifest_invalid",
                    f"Published guidance contains runtime policy: {entry.skill_id}.",
                )
    return len(seen)


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="video_style_skill_validator")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("agent/video-skills"))
    args = parser.parse_args()
    count = validate_video_style_skills(args.root)
    print(f"Validated {count} published Video Style Skill package(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
