"""Creative Method Skill seed catalog: parse, import, and inject.

Seed files are versioned markdown with structured frontmatter. Import is
idempotent by skill id and version; SQLite is the runtime source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError

_CREATIVE_METHOD_REQUIRED_FIELDS: tuple[str, ...] = (
    "skill_id",
    "version",
    "skill_kind",
    "title",
    "core_principle",
    "consumer_psychology",
    "story_structure",
    "hook_methods",
    "product_role",
    "suitable_categories_and_goals",
    "unsuitable_cases",
    "common_mistakes",
    "cross_category_examples",
)

_REQUIRED_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "creative_method": _CREATIVE_METHOD_REQUIRED_FIELDS,
}

_SUMMARY_FIELD_BY_KIND: dict[str, str] = {
    "creative_method": "core_principle",
}

_CROSS_CATEGORY_MIN_EXAMPLES = 2


def creative_method_seed_dir() -> Path:
    """Return the repository seed directory for creative method skills."""

    return Path(__file__).resolve().parents[2] / "seed" / "creative_method_skills"


@dataclass(frozen=True)
class CreativeSkillSeed:
    """One parsed seed skill file."""

    skill_id: str
    version: str
    skill_kind: str
    title: str
    summary: str
    frontmatter: dict[str, str]


def parse_seed_file(path: Path) -> CreativeSkillSeed:
    """Parse one seed markdown file; raise on missing or empty fields."""

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise _invalid(path, "frontmatter delimiter")
    end = text.find("\n---", 3)
    if end < 0:
        raise _invalid(path, "frontmatter delimiter")
    frontmatter = _parse_frontmatter(text[4:end], path)
    skill_kind = frontmatter.get("skill_kind", "").strip()
    required_fields = _REQUIRED_FIELDS_BY_KIND.get(skill_kind)
    if required_fields is None:
        raise _invalid(path, f"unknown skill_kind: {skill_kind[:40] or '<missing>'}")
    for field in required_fields:
        if not frontmatter.get(field, "").strip():
            raise _invalid(path, f"required field {field}")
    if skill_kind == "creative_method":
        examples = _count_examples(frontmatter["cross_category_examples"])
        if examples < _CROSS_CATEGORY_MIN_EXAMPLES:
            raise _invalid(path, "at least two cross-category examples")
    return CreativeSkillSeed(
        skill_id=frontmatter["skill_id"],
        version=frontmatter["version"],
        skill_kind=skill_kind,
        title=frontmatter["title"],
        summary=frontmatter[_SUMMARY_FIELD_BY_KIND[skill_kind]].strip().replace("\n", " "),
        frontmatter=frontmatter,
    )


class CreativeMethodSkillCatalogService:
    """Import seed files and expose the whole-catalog injection boundary."""

    def __init__(
        self,
        database: V2Database,
        seed_dir: Path,
    ) -> None:
        self._database = database
        self._seed_dir = seed_dir
        self._repository = BrandDecisionRepository(database)

    def import_seeds(self) -> int:
        """Import every seed file once; return the count of new inserts."""

        seeds = sorted(self._seed_dir.glob("*.md"))
        inserted = 0
        try:
            with self._database.engine.begin() as connection:
                for path in seeds:
                    seed = parse_seed_file(path)
                    body = json_dumps(seed.frontmatter)
                    created = self._repository.upsert_creative_skill_in_transaction(
                        connection,
                        skill_id=seed.skill_id,
                        version=seed.version,
                        skill_kind=seed.skill_kind,
                        title=seed.title,
                        summary=seed.summary,
                        body_json=body,
                    )
                    inserted += 1 if created else 0
        except V2PersistenceError:
            raise
        except Exception as error:
            raise V2PersistenceError(
                "brand_skill_seed_invalid",
                "Creative skill seed import failed.",
                stage="creative_method_skill_catalog",
            ) from error
        return inserted

    def injection_summaries(self) -> tuple[dict[str, str], ...]:
        """Return the whole-catalog summaries injected into creative-strategy."""

        rows = self._repository.list_creative_skills()
        return tuple(
            {
                "skill_id": row["skill_id"],
                "title": row["title"],
                "summary": row["summary"],
            }
            for row in rows
            if row["skill_kind"] == "creative_method"
        )


def _count_examples(text: str) -> int:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return len(lines)


def _parse_frontmatter(block: str, path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key: str | None = None
    folded_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, folded_lines
        if current_key is not None:
            fields[current_key] = "\n".join(line.strip() for line in folded_lines).strip()
            if not folded_lines:
                fields[current_key] = fields.get(current_key, "").strip()
        current_key = None
        folded_lines = []

    for line in block.splitlines():
        if line.startswith("  ") or (line.startswith(">") is False and line.startswith(" ")):
            if current_key is None:
                raise _invalid(path, "indented line without key")
            folded_lines.append(line.strip())
            continue
        flush()
        if ":" not in line:
            raise _invalid(path, f"unparsable frontmatter line: {line[:40]}")
        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = raw_value.strip()
        if value in {">", ">-", "|", "|-"}:
            current_key = key
            folded_lines = []
        else:
            fields[key] = value
    flush()
    return fields


def json_dumps(fields: dict[str, str]) -> str:
    import json

    return json.dumps(fields, ensure_ascii=False, sort_keys=True)


def _invalid(path: Path, reason: str) -> V2PersistenceError:
    return V2PersistenceError(
        "brand_skill_seed_invalid",
        f"Invalid creative skill seed {path.name}: {reason}",
        stage="creative_method_skill_catalog",
    )
