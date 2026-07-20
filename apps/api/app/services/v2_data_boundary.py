from pathlib import Path


V2_ALLOWED_TOP_LEVEL_DIRS = {"assets", "v2"}
V2_FORBIDDEN_TOP_LEVEL_DIRS = {
    "agent_conversations",
    "asset_library",
    "audio",
    "characters",
    "final",
    "products",
    "runs",
    "scenes",
    "storyboards",
    "subtitles",
    "videos",
    "workflows",
}
V2_FORBIDDEN_RELATIVE_PATHS = {
    Path("assets/images"),
    Path("assets/videos"),
}


class V2DataBoundaryError(RuntimeError):
    code = "v2_data_boundary_violation"

    def __init__(self, *, operation: str, relative_path: str, message: str | None = None) -> None:
        self.operation = operation
        self.relative_path = relative_path
        super().__init__(
            message or f"V2 data boundary violation during {operation}: rejected {relative_path}"
        )


def validate_v2_data_path(data_dir: Path, path: Path | str, *, operation: str) -> Path:
    data_root = data_dir.resolve()
    candidate = Path(path)
    absolute_path = candidate if candidate.is_absolute() else data_root / candidate
    absolute_path = absolute_path.resolve(strict=False)
    try:
        relative_path = absolute_path.relative_to(data_root)
    except ValueError as exc:
        raise V2DataBoundaryError(
            operation=operation,
            relative_path=absolute_path.as_posix(),
            message=(
                f"V2 data boundary violation during {operation}: "
                f"rejected {absolute_path.as_posix()} outside data root"
            ),
        ) from exc
    validate_v2_relative_path(relative_path, operation=operation)
    return absolute_path


def validate_v2_relative_path(path: Path | str, *, operation: str) -> Path:
    relative_path = Path(path)
    if relative_path.is_absolute():
        raise V2DataBoundaryError(
            operation=operation,
            relative_path=relative_path.as_posix(),
            message=(
                f"V2 data boundary violation during {operation}: "
                f"rejected absolute relative path {relative_path.as_posix()}"
            ),
        )
    if not relative_path.parts:
        raise V2DataBoundaryError(operation=operation, relative_path=".")
    if ".." in relative_path.parts:
        raise V2DataBoundaryError(operation=operation, relative_path=relative_path.as_posix())

    top_level = relative_path.parts[0]
    if top_level in V2_FORBIDDEN_TOP_LEVEL_DIRS or top_level not in V2_ALLOWED_TOP_LEVEL_DIRS:
        raise V2DataBoundaryError(operation=operation, relative_path=relative_path.as_posix())

    normalized = Path(*relative_path.parts[:2]) if len(relative_path.parts) >= 2 else relative_path
    if normalized in V2_FORBIDDEN_RELATIVE_PATHS:
        raise V2DataBoundaryError(operation=operation, relative_path=relative_path.as_posix())

    return relative_path
