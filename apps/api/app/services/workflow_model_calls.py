"""Python-owned immutable diagnostic files; never workflow authoring authority."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from app.schemas.workflow_model_calls import (
    WorkflowModelCallDetailV1,
    WorkflowModelCallListV1,
    WorkflowModelCallRecordV1,
    WorkflowModelCallSummaryV1,
    WorkflowModelCallWriteV1,
    WorkflowModelCallReceiptV1,
)
from app.persistence.agent_run_repository import AgentRunRepository, AgentRunRepositoryError
from app.persistence.database import create_v2_database
from app.services.workflow_model_call_redaction import redact_model_call

_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_MAX_RECORD_BYTES = 16 * 1024 * 1024


class WorkflowModelCallError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class WorkflowModelCallStore:
    def __init__(self, data_dir: Path, *, secrets: tuple[str, ...] = ()) -> None:
        self._data_dir = data_dir
        self._secrets = secrets

    def record_for_run(self, write: WorkflowModelCallWriteV1) -> WorkflowModelCallReceiptV1:
        database = create_v2_database(self._data_dir)
        try:
            run = AgentRunRepository(database).load(write.run_id)
        except AgentRunRepositoryError as error:
            missing = error.code == "agent_run_not_found"
            raise WorkflowModelCallError(
                "agent_model_call_run_not_found" if missing else "agent_model_call_unavailable",
                404 if missing else 503,
            ) from error
        finally:
            database.dispose()
        if run.workflow_id:
            self.record(run.workflow_id, run.operation, write)
        return WorkflowModelCallReceiptV1(
            call_id=write.call_id, phase=write.phase, recorded=bool(run.workflow_id)
        )

    def record(self, workflow_id: str, operation: str, write: WorkflowModelCallWriteV1) -> None:
        directory = self._directory(workflow_id)
        safe, paths = redact_model_call(write.payload, self._secrets)
        record = WorkflowModelCallRecordV1(
            **{**write.model_dump(), "payload": safe},
            workflow_id=workflow_id,
            operation=operation,
            redacted_paths=paths,
        )
        if write.phase == "outcome":
            request = self._load(directory / f"{write.call_id}.request.json")
            if (request.run_id, request.stage, request.boundary, request.operation) != (
                write.run_id,
                write.stage,
                write.boundary,
                operation,
            ):
                raise WorkflowModelCallError("agent_model_call_conflict", 409)
        content = json.dumps(
            record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        if len(content.encode("utf-8")) > _MAX_RECORD_BYTES:
            raise WorkflowModelCallError("agent_model_call_too_large", 422)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self._publish(directory / f"{write.call_id}.{write.phase}.json", content)

    def detail(self, workflow_id: str, call_id: str) -> WorkflowModelCallDetailV1:
        if not _ID.fullmatch(call_id):
            raise WorkflowModelCallError("agent_model_call_invalid")
        directory = self._directory(workflow_id)
        request = self._load(directory / f"{call_id}.request.json")
        outcome_path = directory / f"{call_id}.outcome.json"
        outcome = self._load(outcome_path) if outcome_path.exists() else None
        status = "incomplete"
        if outcome is not None:
            status = (
                "failed"
                if outcome.failed
                else "completed"
                if outcome.complete and request.complete
                else "incomplete"
            )
        return WorkflowModelCallDetailV1(
            workflow_id=workflow_id,
            call_id=call_id,
            run_id=request.run_id,
            operation=request.operation,
            stage=request.stage,
            started_at=request.recorded_at,
            status=status,
            request=request,
            outcome=outcome,
        )

    def list(self, workflow_id: str, *, offset: int, limit: int) -> WorkflowModelCallListV1:
        directory = self._directory(workflow_id)
        summaries = []
        paths = sorted(
            directory.glob("*.request.json"), key=lambda path: (path.stat().st_mtime_ns, path.name)
        )
        for path in paths[offset : offset + limit]:
            detail = self.detail(workflow_id, path.name.removesuffix(".request.json"))
            summaries.append(
                WorkflowModelCallSummaryV1.model_validate(
                    detail.model_dump(include=set(WorkflowModelCallSummaryV1.model_fields))
                )
            )
        return WorkflowModelCallListV1(
            workflow_id=workflow_id,
            items=summaries,
            next_offset=offset + limit if offset + limit < len(paths) else None,
        )

    def _directory(self, workflow_id: str) -> Path:
        if not _ID.fullmatch(workflow_id):
            raise WorkflowModelCallError("agent_model_call_invalid")
        root = self._data_dir.resolve()
        directory = root / "v2" / "runs" / workflow_id / "model-calls"
        for candidate in (directory, *directory.parents):
            if candidate == root:
                break
            if candidate.is_symlink():
                raise WorkflowModelCallError("agent_model_call_invalid")
        return directory

    @staticmethod
    def _load(path: Path) -> WorkflowModelCallRecordV1:
        if path.is_symlink():
            raise WorkflowModelCallError("agent_model_call_invalid")
        if not path.is_file():
            raise WorkflowModelCallError("agent_model_call_not_found", 404)
        return WorkflowModelCallRecordV1.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _publish(path: Path, content: str) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".call-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_text(encoding="utf-8") != content:
                    raise WorkflowModelCallError("agent_model_call_conflict", 409) from None
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.unlink(temporary)
