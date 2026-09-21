"""Credential redaction for protected diagnostic content, not replay identity."""

import json
import re
from typing import Any

_KEY = re.compile(
    r"^(?:authorization|proxy.authorization|.*api.?key|.*access.?token|.*refresh.?token|"
    r".*secret.*|password|cookie|set.cookie|credential|signature|x.amz.signature|"
    r"x.goog.signature|sig|token)$",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[^\s\"'\\,;]+", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|"
    r"x-amz-signature|x-amz-credential|x-goog-signature|sig|token)[\"']?\s*[=:]\s*[\"']?)[^\s&\"'<>]+",
    re.IGNORECASE,
)


def redact_model_call(value: Any, secrets: tuple[str, ...] = ()) -> tuple[Any, list[str]]:
    paths: list[str] = []

    def visit(item: Any, path: str, depth: int = 0) -> Any:
        if depth > 64:
            raise ValueError("agent_model_call_invalid")
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                child_path = f"{path}/{key}"
                if _KEY.fullmatch(key):
                    result[key] = "[REDACTED]"
                    paths.append(child_path)
                else:
                    result[key] = visit(child, child_path, depth + 1)
            return result
        if isinstance(item, list):
            return [visit(child, f"{path}/{index}", depth + 1) for index, child in enumerate(item)]
        if not isinstance(item, str):
            return item
        redacted = item
        for secret in sorted((secret for secret in secrets if secret), key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
        redacted = _ASSIGNMENT.sub(r"\1[REDACTED]", redacted)
        redacted = re.sub(r"(https?://)[^/?#@\s]+:[^/?#@\s]+@", r"\1[REDACTED]@", redacted)
        if item.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(item)
                safe = visit(parsed, path, depth + 1)
                if safe != parsed:
                    redacted = json.dumps(safe, ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        if redacted != item or "[REDACTED]" in redacted:
            paths.append(path)
        return redacted

    return visit(value, ""), sorted(set(paths))
