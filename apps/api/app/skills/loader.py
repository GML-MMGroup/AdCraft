from pathlib import Path

from app.skills.base import WorkflowSkill

SKILL_PACKS_DIR = Path(__file__).parent / "skill_packs"


class SkillLoadError(RuntimeError):
    """Raised when a Markdown Skill pack cannot be loaded."""


_CACHE: dict[tuple[str, str], WorkflowSkill] = {}


def clear_skill_cache() -> None:
    _CACHE.clear()


def load_skill(skill_id: str, skill_packs_dir: Path | None = None) -> WorkflowSkill:
    root = skill_packs_dir or SKILL_PACKS_DIR
    cache_key = (root.resolve().as_posix(), skill_id)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    skill_path = root / skill_id / "SKILL.md"
    if not skill_path.exists():
        raise SkillLoadError(f"Skill pack not found for {skill_id}: {skill_path}")

    raw_markdown = skill_path.read_text(encoding="utf-8")
    frontmatter, markdown = _split_frontmatter(raw_markdown)
    loaded_skill_id = frontmatter.get("skill_id", skill_id)
    if loaded_skill_id != skill_id:
        raise SkillLoadError(
            f"Skill id mismatch in {skill_path}: expected {skill_id}, got {loaded_skill_id}"
        )

    skill = WorkflowSkill(
        skill_id=loaded_skill_id,
        name=frontmatter.get("name") or _title_from_skill_id(skill_id),
        description=frontmatter.get("description") or "",
        markdown=markdown.strip(),
        source_path=skill_path,
    )
    _CACHE[cache_key] = skill
    return skill


def _split_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    normalized = markdown.lstrip()
    if not normalized.startswith("---"):
        return {}, markdown
    parts = normalized.split("---", 2)
    if len(parts) < 3:
        raise SkillLoadError("Invalid Skill frontmatter: missing closing ---")
    frontmatter_text = parts[1]
    body = parts[2].lstrip("\n")
    return _parse_frontmatter(frontmatter_text), body


def _parse_frontmatter(frontmatter_text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in frontmatter_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise SkillLoadError(f"Invalid Skill frontmatter line: {raw_line}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def _title_from_skill_id(skill_id: str) -> str:
    return skill_id.replace("_", " ").title()
