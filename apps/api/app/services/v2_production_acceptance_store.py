from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.workflow_v2_production_acceptance import (
    V2ProductionAcceptanceReport,
    V2ProductionAcceptanceRunState,
)
from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_data_path


class V2ProductionAcceptanceStoreError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        acceptance_run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.acceptance_run_id = acceptance_run_id


def hash_idempotency_key(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


class V2ProductionAcceptanceStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._root = self._validated(data_dir / "v2" / "acceptance-runs")
        self._control = self._validated(self._root / ".control")

    def create_run(
        self,
        fixture_id: str,
        idempotency_key_hash: str,
    ) -> V2ProductionAcceptanceRunState:
        with self._locked():
            existing = self._find_idempotent_run_unlocked(idempotency_key_hash)
            if existing is not None:
                if existing.fixture_id != fixture_id:
                    raise V2ProductionAcceptanceStoreError(
                        "production_acceptance_idempotency_conflict",
                        "The idempotency key is already associated with another fixture.",
                    )
                return existing

            now = utc_now().isoformat()
            state = V2ProductionAcceptanceRunState(
                revision=1,
                acceptance_run_id=f"accept_{uuid4().hex[:16]}",
                fixture_id=fixture_id,
                idempotency_key_hash=idempotency_key_hash,
                lifecycle_status="queued",
                technical_verdict="pending",
                current_stage="reserved",
                created_at=now,
                updated_at=now,
            )
            self._atomic_json_write(
                self._state_path(state.acceptance_run_id), state.model_dump(mode="json")
            )
            self._atomic_json_write(
                self._idempotency_path(idempotency_key_hash),
                {
                    "fixture_id": fixture_id,
                    "acceptance_run_id": state.acceptance_run_id,
                    "idempotency_key_hash": idempotency_key_hash,
                },
            )
            return state

    def claim_run(
        self,
        fixture_id: str,
        idempotency_key_hash: str,
    ) -> tuple[V2ProductionAcceptanceRunState, bool]:
        with self._locked():
            existing = self._find_idempotent_run_unlocked(idempotency_key_hash)
            if existing is not None:
                if existing.fixture_id != fixture_id:
                    raise V2ProductionAcceptanceStoreError(
                        "production_acceptance_idempotency_conflict",
                        "The idempotency key is already associated with another fixture.",
                    )
                return existing, True

            active_run_id = self._active_run_id_unlocked()
            if active_run_id:
                active_state = self.load_run(active_run_id)
                if active_state.lifecycle_status in {
                    "completed",
                    "blocked",
                    "failed",
                    "cancelled",
                }:
                    self._remove_active_unlocked()
                else:
                    raise V2ProductionAcceptanceStoreError(
                        "production_acceptance_active_run_exists",
                        "Another production acceptance run is active.",
                        acceptance_run_id=active_run_id,
                    )

            now = utc_now().isoformat()
            state = V2ProductionAcceptanceRunState(
                revision=1,
                acceptance_run_id=f"accept_{uuid4().hex[:16]}",
                fixture_id=fixture_id,
                idempotency_key_hash=idempotency_key_hash,
                lifecycle_status="queued",
                technical_verdict="pending",
                current_stage="reserved",
                created_at=now,
                updated_at=now,
            )
            self._atomic_json_write(
                self._state_path(state.acceptance_run_id),
                state.model_dump(mode="json"),
            )
            self._atomic_json_write(
                self._idempotency_path(idempotency_key_hash),
                {
                    "fixture_id": fixture_id,
                    "acceptance_run_id": state.acceptance_run_id,
                    "idempotency_key_hash": idempotency_key_hash,
                },
            )
            self._atomic_json_write(
                self._active_path(),
                {"acceptance_run_id": state.acceptance_run_id},
            )
            return state, False

    def load_run(self, acceptance_run_id: str) -> V2ProductionAcceptanceRunState:
        path = self._state_path(acceptance_run_id)
        if not path.exists():
            raise V2ProductionAcceptanceStoreError(
                "production_acceptance_run_not_found",
                "Production acceptance run was not found.",
                acceptance_run_id=acceptance_run_id,
            )
        try:
            return V2ProductionAcceptanceRunState.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise self._store_failed() from exc

    def find_idempotent_run(
        self,
        idempotency_key_hash: str,
    ) -> V2ProductionAcceptanceRunState | None:
        with self._locked():
            return self._find_idempotent_run_unlocked(idempotency_key_hash)

    def update_run(
        self,
        acceptance_run_id: str,
        expected_revision: int,
        **updates: Any,
    ) -> V2ProductionAcceptanceRunState:
        with self._locked():
            current = self.load_run(acceptance_run_id)
            if current.revision != expected_revision:
                raise V2ProductionAcceptanceStoreError(
                    "production_acceptance_store_revision_conflict",
                    "Production acceptance state revision is stale.",
                    acceptance_run_id=acceptance_run_id,
                )
            payload = current.model_dump(mode="json")
            payload.update(updates)
            payload["revision"] = current.revision + 1
            payload["updated_at"] = utc_now().isoformat()
            try:
                updated = V2ProductionAcceptanceRunState.model_validate(payload)
            except ValidationError as exc:
                raise self._store_failed() from exc
            self._atomic_json_write(
                self._state_path(acceptance_run_id), updated.model_dump(mode="json")
            )
            return updated

    def reserve_active(self, acceptance_run_id: str) -> None:
        with self._locked():
            path = self._active_path()
            if path.exists():
                try:
                    owner = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise self._store_failed() from exc
                active_run_id = str(owner.get("acceptance_run_id") or "")
                if active_run_id == acceptance_run_id:
                    return
                active_state = self.load_run(active_run_id) if active_run_id else None
                if active_state is not None and active_state.lifecycle_status in {
                    "completed",
                    "blocked",
                    "failed",
                    "cancelled",
                }:
                    path.unlink(missing_ok=True)
                    _fsync_directory(path.parent)
                else:
                    raise V2ProductionAcceptanceStoreError(
                        "production_acceptance_active_run_exists",
                        "Another production acceptance run is active.",
                        acceptance_run_id=active_run_id or None,
                    )
            self._atomic_json_write(path, {"acceptance_run_id": acceptance_run_id})

    def active_run_id(self) -> str | None:
        with self._locked():
            return self._active_run_id_unlocked()

    def release_active(self, acceptance_run_id: str) -> None:
        with self._locked():
            path = self._active_path()
            if not path.exists():
                return
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise self._store_failed() from exc
            if str(payload.get("acceptance_run_id") or "") != acceptance_run_id:
                return
            self._remove_active_unlocked()

    def save_report(
        self,
        report: V2ProductionAcceptanceReport,
    ) -> V2ProductionAcceptanceReport:
        with self._locked():
            self._atomic_json_write(
                self._report_path(report.acceptance_run_id),
                report.model_dump(mode="json"),
            )
        return report

    def load_report(self, acceptance_run_id: str) -> V2ProductionAcceptanceReport | None:
        path = self._report_path(acceptance_run_id)
        if not path.exists():
            return None
        try:
            return V2ProductionAcceptanceReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise V2ProductionAcceptanceStoreError(
                "production_acceptance_report_failed",
                "Production acceptance report could not be read.",
                acceptance_run_id=acceptance_run_id,
            ) from exc

    def report_exists(self, acceptance_run_id: str) -> bool:
        return self._report_path(acceptance_run_id).is_file()

    def report_relative_path(self, acceptance_run_id: str) -> str:
        self._state_path(acceptance_run_id)
        return f"v2/acceptance-runs/{acceptance_run_id}/report.json"

    def save_review_html(self, acceptance_run_id: str, document: str) -> str:
        with self._locked():
            self._atomic_text_write(self._review_path(acceptance_run_id), document)
        return self.review_relative_path(acceptance_run_id)

    def review_exists(self, acceptance_run_id: str) -> bool:
        return self._review_path(acceptance_run_id).is_file()

    def review_relative_path(self, acceptance_run_id: str) -> str:
        self._state_path(acceptance_run_id)
        return f"v2/acceptance-runs/{acceptance_run_id}/review.html"

    def _find_idempotent_run_unlocked(
        self,
        idempotency_key_hash: str,
    ) -> V2ProductionAcceptanceRunState | None:
        path = self._idempotency_path(idempotency_key_hash)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            run_id = str(payload["acceptance_run_id"])
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise self._store_failed() from exc
        return self.load_run(run_id)

    def _active_run_id_unlocked(self) -> str | None:
        path = self._active_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self._store_failed() from exc
        return str(payload.get("acceptance_run_id") or "") or None

    def _remove_active_unlocked(self) -> None:
        path = self._active_path()
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._control.mkdir(parents=True, exist_ok=True)
        lock_path = self._validated(self._control / "store.lock")
        try:
            with lock_path.open("a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except V2ProductionAcceptanceStoreError:
            raise
        except OSError as exc:
            raise self._store_failed() from exc

    def _state_path(self, acceptance_run_id: str) -> Path:
        if (
            not acceptance_run_id.startswith("accept_")
            or Path(acceptance_run_id).name != acceptance_run_id
        ):
            raise V2ProductionAcceptanceStoreError(
                "production_acceptance_run_not_found",
                "Production acceptance run was not found.",
            )
        return self._validated(self._root / acceptance_run_id / "state.json")

    def _idempotency_path(self, key_hash: str) -> Path:
        if len(key_hash) != 64 or any(
            character not in "0123456789abcdef" for character in key_hash
        ):
            raise self._store_failed()
        return self._validated(self._control / "idempotency" / f"{key_hash}.json")

    def _active_path(self) -> Path:
        return self._validated(self._control / "active.json")

    def _report_path(self, acceptance_run_id: str) -> Path:
        self._state_path(acceptance_run_id)
        return self._validated(self._root / acceptance_run_id / "report.json")

    def _review_path(self, acceptance_run_id: str) -> Path:
        self._state_path(acceptance_run_id)
        return self._validated(self._root / acceptance_run_id / "review.html")

    def _validated(self, path: Path) -> Path:
        try:
            return validate_v2_data_path(
                self._data_dir,
                path,
                operation="v2-production-acceptance-store",
            )
        except V2DataBoundaryError as exc:
            raise self._store_failed() from exc

    def _atomic_json_write(self, path: Path, payload: dict[str, Any]) -> None:
        self._atomic_text_write(
            path,
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        )

    def _atomic_text_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise self._store_failed() from exc

    @staticmethod
    def _store_failed() -> V2ProductionAcceptanceStoreError:
        return V2ProductionAcceptanceStoreError(
            "production_acceptance_store_failed",
            "Production acceptance state could not be persisted.",
        )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
