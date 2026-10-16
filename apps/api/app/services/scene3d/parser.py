"""SceneScript parser: extract and validate SceneScript from LLM output.

The LLM is instructed to output only a SceneScript JSON object in a ```json
code block. In practice, LLM output may include wrapping text, markdown
fences, or trailing commentary. This module robustly extracts the JSON,
parses it into SceneScriptRoot, and provides structured error feedback for
retry.

See: docs/3d-previs/prompt-engineering-guide.md (output format enforcement)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.llm_json_salvage import prune_extra_fields, salvage_json_text


@dataclass
class ParseResult:
    """Result of attempting to parse LLM output into SceneScript."""

    success: bool
    scene_script: SceneScriptRoot | None = None
    raw_json: str | None = None
    error: str | None = None
    error_details: list[str] | None = None

    @property
    def retry_feedback(self) -> str | None:
        """Human-readable feedback for LLM retry, or None if successful."""
        if self.success:
            return None
        parts = [f"SceneScript validation failed: {self.error}"]
        if self.error_details:
            parts.extend(f"- {d}" for d in self.error_details[:5])
        parts.append(
            "Output ONLY a valid SceneScript JSON object in a ```json block. "
            "Fix the errors above and ensure all required fields are present."
        )
        return "\n".join(parts)


# JSON code block patterns, tried in order of specificity
_JSON_PATTERNS: list[re.Pattern[str]] = [
    # ```json ... ``` (most common)
    re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE),
    # ``` ... ``` (generic code block)
    re.compile(r"```\s*([\s\S]*?)\s*```"),
    # { ... } (bare JSON object, last resort)
    re.compile(r"(\{[\s\S]*\})"),
]


def extract_json_text(llm_output: str) -> str | None:
    """Extract JSON text from LLM output, handling markdown wrapping.

    Tries code-block patterns first, then bare-object matching.
    Returns the raw JSON string, or None if no JSON-like content found.
    """
    if not llm_output or not llm_output.strip():
        return None

    for pattern in _JSON_PATTERNS:
        match = pattern.search(llm_output)
        if match:
            candidate = match.group(1).strip()
            # Quick sanity: must start with { and contain "scene" key
            if candidate.startswith("{") and '"scene"' in candidate:
                return candidate

    # Last resort: find first { and last }
    first_brace = llm_output.find("{")
    last_brace = llm_output.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = llm_output[first_brace : last_brace + 1].strip()
        if '"scene"' in candidate:
            return candidate

    return None


def parse_llm_output(llm_output: str) -> ParseResult:
    """Parse LLM output into a validated SceneScriptRoot.

    Args:
        llm_output: Raw text returned by the LLM.

    Returns:
        ParseResult with success flag, scene_script on success, or
        structured error details on failure (suitable for LLM retry).
    """
    raw_json = extract_json_text(llm_output)
    if raw_json is None:
        return ParseResult(
            success=False,
            error="No JSON object found in LLM output",
            error_details=[
                "The output must contain a SceneScript JSON object wrapped in ```json ... ```",
                "Ensure the JSON has a top-level 'scene' field",
            ],
        )

    # Parse JSON — with a local salvage pass first (2026-09-29 live: the model
    # emitted a trailing comma and the whole generation died on it).
    data: dict | None = None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        repaired = salvage_json_text(raw_json)
        if repaired is not None:
            try:
                data = json.loads(repaired)
                raw_json = repaired
            except json.JSONDecodeError:
                data = None
        if data is None:
            return ParseResult(
                success=False,
                raw_json=raw_json,
                error=f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}",
                error_details=[
                    "Check for trailing commas, unclosed brackets, or unescaped quotes",
                    f"Error near: ...{raw_json[max(0, exc.pos - 30):exc.pos + 30]}...",
                ],
            )

    # Validate against SceneScript schema
    try:
        scene_script = SceneScriptRoot.model_validate(data)
    except ValidationError as exc:
        # Extra fields the model echoed back (context leakage) are pruned and
        # re-validated before failing — one local retry, no provider call.
        pruned = prune_extra_fields(data, exc.errors())
        if pruned is not None:
            try:
                scene_script = SceneScriptRoot.model_validate(pruned)
                return ParseResult(success=True, scene_script=scene_script, raw_json=raw_json)
            except ValidationError:
                pass
        details = []
        for err in exc.errors():
            loc = " -> ".join(str(loc) for loc in err.get("loc", []))
            msg = err.get("msg", "unknown error")
            details.append(f"{loc}: {msg}")
        return ParseResult(
            success=False,
            raw_json=raw_json,
            error=f"SceneScript validation failed with {len(exc.errors())} error(s)",
            error_details=details,
        )

    return ParseResult(success=True, scene_script=scene_script, raw_json=raw_json)


def parse_with_retry(
    llm_output: str,
    max_retries: int = 2,
) -> ParseResult:
    """Parse with built-in retry logic.

    This is a convenience wrapper. The actual LLM retry call should be
    handled by the caller (workflow_node_executor), using
    ParseResult.retry_feedback as the retry instruction.

    Args:
        llm_output: Raw LLM output.
        max_retries: Kept for API compatibility; actual retries are caller-driven.

    Returns:
        ParseResult.
    """
    return parse_llm_output(llm_output)
