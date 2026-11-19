"""Collect independent screenplay grounding diagnostics before nested schema validation."""

from difflib import SequenceMatcher
from typing import Any, Iterator

from app.schemas.agent_runtime import StructuredViolation


def screenplay_grounding_violations(value: dict[str, Any]) -> tuple[StructuredViolation, ...]:
    """Report repairable evidence errors without modifying or accepting model content.

    The typed contract remains the acceptance authority. Inspect only well-typed
    inputs here so a malformed inventory cannot hide independent quote problems.
    """
    violations: list[StructuredViolation] = []

    def report(path: str, message: str, expected: Any = None, actual: Any = None) -> None:
        violations.append(
            StructuredViolation(
                code="brand_screenplay_grounding_invalid",
                message=message,
                field_path=path,
                expected=expected,
                actual=actual,
            )
        )

    for field in ("title", "screenplay"):
        text = value.get(field)
        if isinstance(text, str) and not text.strip():
            report(field, "Supply nonblank screenplay text.")

    inventory = value.get("production_requirements")
    if isinstance(inventory, dict):
        count = inventory.get("character_count")
        characters = inventory.get("characters", [])
        if count is None:
            report(
                "production_requirements.character_count", "Resolve the screenplay's cast count."
            )
        elif isinstance(count, int) and isinstance(characters, list) and count != len(characters):
            report(
                "production_requirements.character_count",
                "The resolved cast count must match the character inventory.",
                len(characters),
                count,
            )
        for field, resolved in (
            ("character_sources", count is not None),
            ("prop_sources", inventory.get("prop_presence") in ("include", "exclude")),
            ("scene_sources", inventory.get("scene_presence") in ("include", "exclude")),
        ):
            if resolved and inventory.get(field, []) == []:
                report(
                    f"production_requirements.{field}",
                    "Supply screenplay evidence for this resolved decision, including exclusion "
                    "or a zero count. Use step_key='story', section_key='screenplay', and copy "
                    "an exact source quote. If the declaration is absent, state the grounded "
                    "decision in the screenplay without changing its story.",
                )
        presence = inventory.get("scene_presence", "unspecified")
        scenes = inventory.get("scenes", [])
        if presence == "unspecified":
            report("production_requirements.scene_presence", "Resolve the screenplay's locations.")
        elif isinstance(scenes, list) and (
            (presence == "include" and not scenes) or (presence == "exclude" and scenes)
        ):
            report(
                "production_requirements.scenes",
                "Scene inventory must agree with its presence decision.",
            )

    screenplay = value.get("screenplay")
    if not isinstance(screenplay, str) or not screenplay.strip():
        return tuple(violations[:128])

    def check_quote(path: str, quote: Any) -> None:
        if not isinstance(quote, str):
            return  # Structural errors are reported by the typed contract.
        if quote.strip() and quote in screenplay:
            return
        expected: dict[str, str] = {"requirement": "A nonblank exact substring of screenplay."}
        excerpt = _source_excerpt(screenplay, quote)
        if excerpt is not None:
            expected["source_excerpt"] = excerpt
        report(
            path,
            "Copy the relevant screenplay text exactly, preserving Markdown markers, "
            "punctuation and whitespace. A source_excerpt is a candidate from the original "
            "text; verify its relevance and copy an unchanged span. Do not rewrite the "
            "story merely to match an incorrect quote.",
            expected,
            quote[:1000],
        )

    for field in ("music_requirement", "timing"):
        section = value.get(field)
        if isinstance(section, dict):
            check_quote(f"{field}.source_quote", section.get("source_quote"))
    if isinstance(inventory, dict):
        for path, source in _inventory_sources(inventory):
            for field, expected in (("step_key", "story"), ("section_key", "screenplay")):
                actual = source.get(field)
                if isinstance(actual, str) and actual != expected:
                    report(
                        f"{path}.{field}",
                        "Use the current screenplay as source authority.",
                        expected,
                        actual[:160],
                    )
            check_quote(f"{path}.quote", source.get("quote"))
    return tuple(violations[:128])


def _inventory_sources(inventory: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    def sources(path: str, items: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        if isinstance(items, list):
            for index, item in enumerate(items):
                if isinstance(item, dict):
                    yield f"{path}.{index}", item

    for field in ("character_sources", "scene_sources", "prop_sources"):
        yield from sources(f"production_requirements.{field}", inventory.get(field))
    for field in ("characters", "scenes", "objects"):
        elements = inventory.get(field)
        if isinstance(elements, list):
            for index, element in enumerate(elements):
                if isinstance(element, dict):
                    yield from sources(
                        f"production_requirements.{field}.{index}.sources", element.get("sources")
                    )


def _source_excerpt(screenplay: str, quote: str) -> str | None:
    """Suggest original text for feedback only; similarity never grants acceptance."""
    if not quote.strip():
        return None
    candidates = [line for line in screenplay.splitlines() if line.strip() and len(line) <= 1000]
    if not candidates:
        return None
    ranked = (
        (SequenceMatcher(None, quote[:1000], line, autojunk=False).ratio(), line)
        for line in candidates
    )
    score, line = max(ranked, key=lambda item: item[0])
    return line if score >= 0.5 else None
