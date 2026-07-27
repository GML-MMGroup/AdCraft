from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkflowSkill:
    skill_id: str
    name: str
    description: str
    markdown: str
    source_path: Path

    def apply(self, context: dict[str, Any]) -> dict[str, Any]:
        key_points = _context_key_points(context)
        return {
            "summary": f"{self.name}: {self.description}",
            "key_points": key_points,
            "prompt_notes": self.disclosed_markdown(),
        }

    def build_prompt(self, context: dict[str, Any]) -> str:
        return (
            f"Skill: {self.name}\n"
            f"Purpose: {self.description}\n"
            "Skill guidance:\n"
            f"{self.disclosed_markdown()}\n"
            f"Input summary: {_summarize_context(context)}"
        )

    def disclosed_markdown(self) -> str:
        return _select_markdown_sections(
            self.markdown,
            {"Purpose", "Output Guidance", "Prompt Rules", "Do Not"},
        )


def _context_key_points(context: dict[str, Any]) -> list[str]:
    keys = list(context.keys())[:4]
    return [f"input:{key}" for key in keys] or ["input:empty"]


def _summarize_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _summarize_context(item) for key, item in list(value.items())[:8]}
    if isinstance(value, list):
        return [_summarize_context(item) for item in value[:4]]
    if isinstance(value, str) and len(value) > 240:
        return value[:240] + "..."
    return value


def _select_markdown_sections(markdown: str, selected_headings: set[str]) -> str:
    selected_lines: list[str] = []
    current_heading: str | None = None
    include_current = False
    for line in markdown.splitlines():
        heading = _heading_title(line)
        if heading is not None:
            current_heading = heading
            include_current = current_heading in selected_headings
        if include_current:
            selected_lines.append(line)
    return "\n".join(selected_lines).strip()


def _heading_title(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    title = stripped.lstrip("#").strip()
    return title or None
