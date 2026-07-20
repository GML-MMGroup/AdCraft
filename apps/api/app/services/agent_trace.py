import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.services.llm_context_sanitizer import sanitize_context_for_llm_text


_TRACE_FILE_LOCK = Lock()


@dataclass
class AgentTraceWriter:
    data_dir: Path
    workflow_id: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_FILE_LOCK:
            if self.trace_path.exists():
                self.entries = self._load()
            else:
                self._save()

    @property
    def trace_path(self) -> Path:
        return self.data_dir / "runs" / self.workflow_id / "trace.json"

    def append(
        self,
        *,
        agent: str,
        model: str | None,
        prompt: str,
        output: Any,
        error: str | None,
        started_at: datetime,
        finished_at: datetime,
        duration_ms: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "agent": agent,
            "model": model,
            "input": {"prompt": sanitize_context_for_llm_text(prompt)},
            "output": sanitize_context_for_llm_text(output),
            "error": error,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
        }
        if metadata:
            entry.update(sanitize_context_for_llm_text(metadata))
        with self._lock, _TRACE_FILE_LOCK:
            self.entries = self._load()
            self.entries.append(entry)
            self._save()

    def _load(self) -> list[dict[str, Any]]:
        if not self.trace_path.exists():
            return []
        return json.loads(self.trace_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        temporary_path = self.trace_path.with_name(f"{self.trace_path.name}.{uuid4().hex}.tmp")
        temporary_path.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.trace_path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class V2AgentTraceWriter(AgentTraceWriter):
    @property
    def trace_path(self) -> Path:
        from app.services.v2_data_boundary import validate_v2_data_path

        return validate_v2_data_path(
            self.data_dir,
            self.data_dir / "v2" / "runs" / self.workflow_id / "trace.json",
            operation="v2-agent-trace",
        )
