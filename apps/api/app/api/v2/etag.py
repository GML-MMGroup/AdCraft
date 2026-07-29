"""Strong ETag rendering and parsing for V2 authoring resources."""

from __future__ import annotations

import re


_WORKFLOW_MUTATION_PATTERN = re.compile(r"^/api/v2/workflows/(?P<workflow_id>[^/]+)(?:/.*)?$")
_OPERATIONAL_MUTATION_PATTERNS = (
    re.compile(r"^/run$"),
    re.compile(r"/(?:generate|regenerate)$"),
    re.compile(r"^/final-composition/render$"),
    re.compile(r"/provider-tasks(?:/|$)"),
    re.compile(r"/executions/[^/]+/(?:resume|cancel)$"),
    re.compile(r"/working-version/discard$"),
    re.compile(r"/renders/[^/]+/cancel$"),
)


class V2PreconditionError(ValueError):
    """Bounded HTTP precondition failure without persistence details."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def workflow_etag(workflow_id: str, state_version: int) -> str:
    """Render the exact strong Workflow authoring ETag."""

    return _render_etag("workflow", workflow_id, state_version)


def project_etag(project_id: str, project_version: int) -> str:
    """Render the exact strong Project metadata ETag."""

    return _render_etag("project", project_id, project_version)


def semantic_workflow_mutation_id(method: str, path: str) -> str | None:
    """Return the Workflow ID when a request consumes semantic authoring state."""

    if method.upper() not in {"POST", "PATCH", "PUT", "DELETE"}:
        return None
    match = _WORKFLOW_MUTATION_PATTERN.fullmatch(path)
    if match is None:
        return None
    workflow_id = match.group("workflow_id")
    if workflow_id in {"plan-from-chat", "plan-from-prompt"}:
        return None
    suffix = path[match.end("workflow_id") :]
    if suffix == "/chat-target":
        return None
    if any(pattern.search(suffix) for pattern in _OPERATIONAL_MUTATION_PATTERNS):
        return None
    return workflow_id


def parse_workflow_if_match(
    value: str | None,
    workflow_id: str,
    *,
    required: bool,
) -> int | None:
    """Parse one strong Workflow If-Match value."""

    return _parse_if_match(
        value,
        resource="workflow",
        resource_id=workflow_id,
        required=required,
    )


def parse_project_if_match(value: str | None, project_id: str) -> int:
    """Parse the mandatory strong Project If-Match value."""

    parsed = _parse_if_match(
        value,
        resource="project",
        resource_id=project_id,
        required=True,
    )
    assert parsed is not None
    return parsed


def _render_etag(resource: str, resource_id: str, version: int) -> str:
    if not resource_id or version < 1:
        raise ValueError("ETag resource identity and version must be positive.")
    return f'"{resource}-{resource_id}-v{version}"'


def _parse_if_match(
    value: str | None,
    *,
    resource: str,
    resource_id: str,
    required: bool,
) -> int | None:
    if value is None or not value.strip():
        if not required:
            return None
        raise V2PreconditionError(
            f"{resource}_precondition_required",
            f"If-Match is required for {resource} mutations.",
            status_code=428,
        )
    pattern = rf'"{re.escape(resource)}-{re.escape(resource_id)}-v([1-9][0-9]*)"'
    match = re.fullmatch(pattern, value.strip())
    if match is None:
        raise V2PreconditionError(
            f"{resource}_state_conflict",
            f"If-Match must contain the current {resource} ETag.",
            status_code=412,
        )
    return int(match.group(1))
