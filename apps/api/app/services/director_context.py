import json
from pathlib import Path

from app.schemas.director_context import DirectorContext


def director_context_path(data_dir: Path, workflow_id: str) -> Path:
    return data_dir / "workflows" / workflow_id / "director_context.json"


def save_director_context(data_dir: Path, context: DirectorContext) -> None:
    path = director_context_path(data_dir, context.workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(context.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def load_director_context(data_dir: Path, workflow_id: str) -> DirectorContext | None:
    path = director_context_path(data_dir, workflow_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return DirectorContext.model_validate(payload)
