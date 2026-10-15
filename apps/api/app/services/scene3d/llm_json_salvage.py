"""Local salvage for common LLM structured-output breakage.

2026-09-29 live findings this module exists for:

* Scene-script generation died on ``Invalid JSON: Expecting ',' delimiter``
  (a trailing comma) — the JSON was one character away from valid.
* The same generator fails with ``LLM returned an empty message`` when a
  reasoning model burns its whole output budget on reasoning.

Both are salvaged locally: repair the JSON text and re-validate before
spending anything, and turn an empty message into a deterministic rough
draft instead of a dead end.  Repo philosophy: degradation must be named
and never silent.
"""

from __future__ import annotations

import json
import re

#: `,` before a closing brace/bracket — the single most common LLM JSON slip.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_FENCED_BLOCK = re.compile(r"```(?:json5?|jsonc)?\s*([\s\S]*?)```", re.IGNORECASE)


def salvage_json_text(raw: str) -> str | None:
    """Return a JSON-parseable object text extracted/repaired from ``raw``.

    Tries, in order: fenced blocks, the outermost balanced ``{...}`` slice,
    and the raw text itself — each with a trailing-comma repair pass.
    Returns the repaired JSON *text* (so callers can report it), or None.
    """

    if not raw or not raw.strip():
        return None
    candidates: list[str] = []
    candidates.extend(block.strip() for block in _FENCED_BLOCK.findall(raw))
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last > first:
        candidates.append(raw[first : last + 1])
    candidates.append(raw)
    for candidate in candidates:
        text = candidate.strip()
        if not text.startswith("{"):
            continue
        for variant in (text, _TRAILING_COMMA.sub(r"\1", text)):
            try:
                parsed = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return variant
    return None


def prune_extra_fields(data: dict, errors: list) -> dict | None:
    """Drop keys pydantic flagged ``extra_forbidden`` and return the pruned dict.

    Returns None when nothing was prunable (caller keeps the original error).
    """

    pruned = dict(data)
    removed = 0
    for error in errors:
        if error.get("type") != "extra_forbidden":
            continue
        loc = error.get("loc") or ()
        cursor: dict = pruned
        for segment in loc[:-1]:
            if not isinstance(cursor, dict) or segment not in cursor:
                cursor = {}
                break
            nxt = cursor[segment]
            if not isinstance(nxt, dict):
                cursor = {}
                break
            cursor = nxt
        leaf = loc[-1] if loc else None
        if leaf is not None and isinstance(cursor, dict) and leaf in cursor:
            del cursor[leaf]
            removed += 1
    return pruned if removed else None
