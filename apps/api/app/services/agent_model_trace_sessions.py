"""Python-owned persistence and replay cursors for Agent model trace evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Literal, Sequence

from app.schemas.agent_model_trace import (
    AgentModelTraceBundleV1,
    AgentModelTraceClaimRequestV1,
    AgentModelTraceClaimResponseV1,
    AgentModelTraceEntryV1,
    AgentModelTraceRecordRequestV1,
    AgentModelTraceRecordReceiptV1,
    canonical_model_trace_bundle_digest,
    canonical_model_trace_entry_digest,
    canonical_model_trace_request_digest,
)


EVIDENCE_ROOT = Path("/data/wenwu.meng/adcraft-evidence")
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "agent_model_replay"


class AgentModelTraceSessionError(RuntimeError):
    """A safe, bounded trace session failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_agent_model_trace_path(
    path: Path,
    *,
    trusted_roots: Sequence[Path] = (EVIDENCE_ROOT, FIXTURE_ROOT),
    must_exist: bool,
) -> Path:
    """Resolve a trace file without accepting a symlink or root escape."""

    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    for parent in (candidate, *candidate.parents):
        if parent.exists() and parent.is_symlink():
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (FileNotFoundError, OSError) as error:
        raise AgentModelTraceSessionError("acceptance_model_trace_invalid") from error
    allowed = False
    for root in trusted_roots:
        try:
            resolved.relative_to(root.resolve(strict=True))
            allowed = True
            break
        except (ValueError, FileNotFoundError, OSError):
            continue
    if not allowed or (must_exist and not resolved.is_file()):
        raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
    return resolved


class AgentModelTraceSessionService:
    """Own one live writer or one immutable-bundle replay cursor."""

    def __init__(
        self,
        *,
        session_id: str,
        mode: Literal["live_record", "replay"],
        bundle_path: Path,
        trusted_roots: Sequence[Path],
        bundle_metadata: dict[str, object] | None = None,
        replay_bundle: AgentModelTraceBundleV1 | None = None,
    ) -> None:
        self.session_id = session_id
        self.mode = mode
        self.bundle_path = bundle_path
        self._trusted_roots = tuple(trusted_roots)
        self._bundle_metadata = dict(bundle_metadata or {})
        self._bundle = replay_bundle
        self._entries: list[AgentModelTraceEntryV1] = []
        self._record_receipts: dict[str, AgentModelTraceRecordReceiptV1] = {}
        self._record_request_digests: dict[str, str] = {}
        self._claim_receipts: dict[str, AgentModelTraceClaimResponseV1] = {}
        self._claim_request_digests: dict[str, str] = {}
        self._cursor = 0
        self._sealed: AgentModelTraceBundleV1 | None = None
        self._lock = threading.RLock()

    @classmethod
    def create_live_record(
        cls,
        *,
        session_id: str,
        bundle_path: Path,
        trusted_roots: Sequence[Path] = (EVIDENCE_ROOT,),
        fixture_id: str,
        profile_id: str,
        source_acceptance_run_id: str,
        source_attempt_id: str,
        source_workflow_id: str | None = None,
        source_project_id: str | None = None,
        parent_bundle_digest: str | None = None,
    ) -> "AgentModelTraceSessionService":
        resolved = validate_agent_model_trace_path(
            bundle_path,
            trusted_roots=trusted_roots,
            must_exist=False,
        )
        return cls(
            session_id=session_id,
            mode="live_record",
            bundle_path=resolved,
            trusted_roots=trusted_roots,
            bundle_metadata={
                "schema_version": "1",
                "fixture_id": fixture_id,
                "profile_id": profile_id,
                "source_acceptance_run_id": source_acceptance_run_id,
                "source_attempt_id": source_attempt_id,
                "source_workflow_id": source_workflow_id,
                "source_project_id": source_project_id,
                "trace_mode": "live_record",
                "parent_bundle_digest": parent_bundle_digest,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @classmethod
    def load_replay(
        cls,
        *,
        session_id: str,
        bundle_path: Path,
        expected_bundle_digest: str,
        trusted_roots: Sequence[Path] = (EVIDENCE_ROOT, FIXTURE_ROOT),
    ) -> "AgentModelTraceSessionService":
        resolved = validate_agent_model_trace_path(
            bundle_path,
            trusted_roots=trusted_roots,
            must_exist=True,
        )
        try:
            bundle = AgentModelTraceBundleV1.model_validate_json(
                resolved.read_text(encoding="utf-8")
            )
        except Exception as error:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid") from error
        if bundle.bundle_digest != expected_bundle_digest:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        return cls(
            session_id=session_id,
            mode="replay",
            bundle_path=resolved,
            trusted_roots=trusted_roots,
            replay_bundle=bundle,
        )

    @property
    def consumed_count(self) -> int:
        return self._cursor

    @property
    def unused_count(self) -> int:
        return len(self._bundle.entries) - self._cursor if self._bundle is not None else 0

    @property
    def bundle_digest(self) -> str | None:
        bundle = self._sealed or self._bundle
        return bundle.bundle_digest if bundle is not None else None

    def record_attempt(
        self,
        request: AgentModelTraceRecordRequestV1,
    ) -> AgentModelTraceRecordReceiptV1:
        if self.mode != "live_record" or request.session_id != self.session_id:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        request_digest = _record_request_digest(request)
        with self._lock:
            if self._sealed is not None:
                raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
            existing = self._record_receipts.get(request.attempt_id)
            if existing is not None:
                if self._record_request_digests[request.attempt_id] != request_digest:
                    raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
                return existing.model_copy(update={"replayed": True})
            sequence_no = len(self._entries) + 1
            values: dict[str, object] = {
                "sequence_no": sequence_no,
                "attempt_id": request.attempt_id,
                "recorded_agent_run_id": request.recorded_agent_run_id,
                "request_identity": request.request_identity,
                "response": request.response,
                "created_at": datetime.now(timezone.utc),
            }
            values["entry_digest"] = canonical_model_trace_entry_digest(values)
            entry = AgentModelTraceEntryV1.model_validate(values)
            receipt = AgentModelTraceRecordReceiptV1(
                session_id=self.session_id,
                attempt_id=request.attempt_id,
                sequence_no=sequence_no,
                entry_digest=entry.entry_digest,
            )
            self._entries.append(entry)
            self._record_receipts[request.attempt_id] = receipt
            self._record_request_digests[request.attempt_id] = request_digest
            self._write_partial()
            return receipt

    def seal(
        self,
        *,
        terminal_disposition: Literal["handled_success", "handled_failure"],
        terminal_failure_code: str | None = None,
    ) -> AgentModelTraceBundleV1:
        if self.mode != "live_record":
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        with self._lock:
            if self._sealed is not None:
                if (
                    self._sealed.terminal_disposition == terminal_disposition
                    and self._sealed.terminal_failure_code == terminal_failure_code
                ):
                    return self._sealed
                raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
            values = {
                **self._bundle_metadata,
                "entries": tuple(self._entries),
                "terminal_disposition": terminal_disposition,
                "terminal_failure_code": terminal_failure_code,
                "sealed_at": datetime.now(timezone.utc),
            }
            values["bundle_digest"] = canonical_model_trace_bundle_digest(values)
            try:
                bundle = AgentModelTraceBundleV1.model_validate(values)
            except Exception as error:
                raise AgentModelTraceSessionError("acceptance_model_trace_invalid") from error
            _atomic_write_json(self.bundle_path, bundle.model_dump(mode="json"))
            self.bundle_path.with_suffix(".partial.json").unlink(missing_ok=True)
            self._sealed = bundle
            return bundle

    def claim_attempt(
        self,
        request: AgentModelTraceClaimRequestV1,
    ) -> AgentModelTraceClaimResponseV1:
        if self.mode != "replay" or request.session_id != self.session_id or self._bundle is None:
            raise AgentModelTraceSessionError("acceptance_model_replay_forbidden")
        request_digest = canonical_model_trace_request_digest(request.request_identity)
        with self._lock:
            existing = self._claim_receipts.get(request.attempt_id)
            if existing is not None:
                if self._claim_request_digests[request.attempt_id] != request_digest:
                    raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
                return existing.model_copy(update={"replayed": True})
            if self._cursor >= len(self._bundle.entries):
                raise AgentModelTraceSessionError("acceptance_model_replay_miss")
            entry = self._bundle.entries[self._cursor]
            if canonical_model_trace_request_digest(entry.request_identity) != request_digest:
                raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
            response = AgentModelTraceClaimResponseV1(
                session_id=self.session_id,
                attempt_id=request.attempt_id,
                sequence_no=entry.sequence_no,
                entry_digest=entry.entry_digest,
                response=entry.response,
            )
            self._cursor += 1
            self._claim_receipts[request.attempt_id] = response
            self._claim_request_digests[request.attempt_id] = request_digest
            return response

    def _write_partial(self) -> None:
        payload = {
            **self._bundle_metadata,
            "entries": [entry.model_dump(mode="json") for entry in self._entries],
            "sealed": False,
        }
        _atomic_write_json(self.bundle_path.with_suffix(".partial.json"), payload)


def _record_request_digest(request: AgentModelTraceRecordRequestV1) -> str:
    payload = request.model_dump(mode="json", exclude={"session_id"})
    return canonical_model_trace_request_digest(request.request_identity) + ":" + _json_digest(payload)


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    from hashlib import sha256

    return sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    encoded = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
