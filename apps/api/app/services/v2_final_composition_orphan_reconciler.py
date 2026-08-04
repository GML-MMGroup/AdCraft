from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from pydantic import BaseModel, Field

from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_provider_result_store import V2ProviderResultStore
from app.services.v2_workflow_lock import v2_workflow_lock

PathResolver = Callable[[str], set[Path]]
ManifestReconciler = Callable[[str], None]
_GRACE_PERIOD = timedelta(hours=24)
_ACTIVE_RENDER_STATUSES = {"queued", "running", "waiting", "cancellation_requested"}


class V2FinalCompositionCleanupError(BaseModel):
    code: str
    path: str | None = None
    message: str


class V2FinalCompositionCleanupCandidate(BaseModel):
    path: str
    size_bytes: int = Field(ge=0)
    mtime: str
    first_seen_orphan_at: str
    reason: str


class V2FinalCompositionCleanupReport(BaseModel):
    cleanup_id: str
    workflow_id: str
    observed_at: str
    marked_paths: list[str] = Field(default_factory=list)
    deleted_paths: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(default_factory=list)
    candidates: list[V2FinalCompositionCleanupCandidate] = Field(default_factory=list)
    errors: list[V2FinalCompositionCleanupError] = Field(default_factory=list)


class V2FinalCompositionOrphanReconciler:
    """Conservative two-pass cleanup scoped to one workflow's final outputs."""

    def __init__(
        self,
        data_dir: Path,
        *,
        registered_paths: PathResolver | None = None,
        active_paths: PathResolver | None = None,
        pending_manifest_paths: PathResolver | None = None,
        terminal_execution_paths: PathResolver | None = None,
        manifest_reconciler: ManifestReconciler | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._asset_store = V2AssetStoreService(data_dir)
        self._provider_results = V2ProviderResultStore(data_dir)
        self._registered_paths = registered_paths or self._default_registered_paths
        self._active_paths = active_paths or self._default_active_paths
        self._pending_manifest_paths = (
            pending_manifest_paths or self._default_pending_manifest_paths
        )
        self._terminal_execution_paths = terminal_execution_paths or (lambda _workflow_id: set())
        self._manifest_reconciler = manifest_reconciler or (lambda _workflow_id: None)

    def reconcile(
        self,
        workflow_id: str,
        *,
        now: datetime | None = None,
    ) -> V2FinalCompositionCleanupReport:
        observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cleanup_id = f"cleanup_{observed_at.strftime('%Y%m%dT%H%M%S%fZ')}"
        report = V2FinalCompositionCleanupReport(
            cleanup_id=cleanup_id,
            workflow_id=workflow_id,
            observed_at=observed_at.isoformat(),
        )
        try:
            self._manifest_reconciler(workflow_id)
        except Exception as exc:  # noqa: BLE001 - maintenance must not fail callers.
            report.errors.append(
                V2FinalCompositionCleanupError(
                    code="cleanup_manifest_reconciliation_failed",
                    message=str(exc)[:500],
                )
            )
        previous = self._previous_candidates(workflow_id)
        protected = self._protection_paths(workflow_id)
        for candidate in self._candidate_paths(workflow_id):
            relative = candidate.relative_to(self._data_dir).as_posix()
            if candidate in protected:
                report.protected_paths.append(relative)
                continue
            try:
                candidate.stat()
            except OSError as exc:
                report.errors.append(
                    V2FinalCompositionCleanupError(
                        code="cleanup_inspection_failed",
                        path=relative,
                        message=str(exc)[:500],
                    )
                )
                continue
            first_seen = previous.get(relative)
            if first_seen is None:
                first_seen = observed_at
                report.marked_paths.append(relative)
                report.candidates.append(
                    self._candidate_record(candidate, first_seen, "unregistered_final_output")
                )
                continue
            if observed_at - first_seen < _GRACE_PERIOD:
                report.candidates.append(
                    self._candidate_record(candidate, first_seen, "orphan_grace_period")
                )
                continue
            with v2_workflow_lock(self._data_dir, workflow_id):
                if candidate in self._protection_paths(workflow_id):
                    report.protected_paths.append(relative)
                    continue
                try:
                    candidate.unlink()
                    report.deleted_paths.append(relative)
                    self._remove_empty_attempt_directories(
                        candidate.parent,
                        workflow_id=workflow_id,
                    )
                except OSError as exc:
                    report.errors.append(
                        V2FinalCompositionCleanupError(
                            code="cleanup_delete_failed",
                            path=relative,
                            message=str(exc)[:500],
                        )
                    )
                    report.candidates.append(
                        self._candidate_record(candidate, first_seen, "delete_failed")
                    )
        self._write_report(report)
        return report

    def has_state(self, workflow_id: str) -> bool:
        return any(root.exists() for root in self._allowlisted_roots(workflow_id))

    def _candidate_paths(self, workflow_id: str) -> list[Path]:
        candidates: list[Path] = []
        for root in self._allowlisted_roots(workflow_id):
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if self._is_candidate(path, root):
                    candidates.append(path.resolve())
        return candidates

    def _is_candidate(self, path: Path, root: Path) -> bool:
        if "final-composition" in root.parts:
            return True
        if path.name in {"state.json", "simple-sequence-plan.json"}:
            return False
        return (
            path.suffix.lower() in {".mp4", ".mov", ".mkv", ".part", ".tmp"}
            or "normalized" in path.name
            or "intermediate" in path.name
        )

    def _allowlisted_roots(self, workflow_id: str) -> tuple[Path, Path]:
        return (
            validate_v2_data_path(
                self._data_dir,
                self._data_dir / "v2" / "runs" / workflow_id / "composition",
                operation="v2-final-composition-cleanup-runtime",
            ),
            validate_v2_data_path(
                self._data_dir,
                self._data_dir / "assets" / "generated" / workflow_id / "final-composition",
                operation="v2-final-composition-cleanup-canonical",
            ),
        )

    def _remove_empty_attempt_directories(
        self,
        directory: Path,
        *,
        workflow_id: str,
    ) -> None:
        roots = self._allowlisted_roots(workflow_id)
        root = next(
            (
                candidate_root
                for candidate_root in roots
                if directory == candidate_root or directory.is_relative_to(candidate_root)
            ),
            None,
        )
        if root is None:
            return
        current = directory
        while current != root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _protection_paths(self, workflow_id: str) -> set[Path]:
        paths = {
            *self._registered_paths(workflow_id),
            *self._active_paths(workflow_id),
            *self._pending_manifest_paths(workflow_id),
        }
        return {self._absolute(path) for path in paths}

    def _default_registered_paths(self, workflow_id: str) -> set[Path]:
        records = self._asset_store.list_asset_versions_for_slot(
            workflow_id=workflow_id,
            slot_id="final-composition-1:final_video",
        )
        return {self._data_dir / record.file_path for record in records}

    def _default_active_paths(self, workflow_id: str) -> set[Path]:
        composition_root = self._allowlisted_roots(workflow_id)[0]
        if not composition_root.exists():
            return set()
        paths: set[Path] = set()
        for state_path in composition_root.glob("render_*/state.json"):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if state.get("status") not in _ACTIVE_RENDER_STATUSES:
                continue
            paths.update(
                path
                for path in state_path.parent.rglob("*")
                if path.is_file() and path.name != "state.json"
            )
        return paths

    def _default_pending_manifest_paths(self, workflow_id: str) -> set[Path]:
        paths: set[Path] = set()
        for manifest in self._provider_results.list_manifests(workflow_id=workflow_id):
            if manifest.commit_status != "pending":
                continue
            for output in manifest.outputs:
                paths.add(self._data_dir / output.staging_path)
        return paths

    def _previous_candidates(self, workflow_id: str) -> dict[str, datetime]:
        root = self._report_root(workflow_id)
        if not root.exists():
            return {}
        paths = sorted(root.glob("cleanup_*.json"))
        if not paths:
            return {}
        try:
            previous = V2FinalCompositionCleanupReport.model_validate_json(
                paths[-1].read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return {}
        return {
            candidate.path: datetime.fromisoformat(candidate.first_seen_orphan_at)
            for candidate in previous.candidates
        }

    def _candidate_record(
        self,
        path: Path,
        first_seen: datetime,
        reason: str,
    ) -> V2FinalCompositionCleanupCandidate:
        stat = path.stat()
        return V2FinalCompositionCleanupCandidate(
            path=path.relative_to(self._data_dir).as_posix(),
            size_bytes=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            first_seen_orphan_at=first_seen.isoformat(),
            reason=reason,
        )

    def _write_report(self, report: V2FinalCompositionCleanupReport) -> None:
        root = self._report_root(report.workflow_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{report.cleanup_id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _report_root(self, workflow_id: str) -> Path:
        return validate_v2_data_path(
            self._data_dir,
            self._data_dir
            / "v2"
            / "runs"
            / workflow_id
            / "maintenance"
            / "final-composition-cleanup",
            operation="v2-final-composition-cleanup-report",
        )

    def _absolute(self, path: Path) -> Path:
        return (path if path.is_absolute() else self._data_dir / path).resolve()
