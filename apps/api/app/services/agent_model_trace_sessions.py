"""Python-owned persistence and replay cursors for Agent model trace evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Literal, Mapping, Sequence

from app.schemas.agent_model_trace import (
    AgentModelTraceBundleV1,
    AgentModelTraceClaimRequestV1,
    AgentModelTraceClaimResponseV1,
    AgentModelTraceEntryV1,
    AgentModelTraceRecordRequestV1,
    AgentModelTraceRecordReceiptV1,
    AgentModelTraceSealReceiptV1,
    AgentModelTraceSealRequestV1,
    AgentModelTraceSessionStatusV1,
    AgentModelTraceRequestSnapshotV1,
    AgentRuntimeAcceptanceReplaySourceV1,
    canonical_model_trace_bundle_digest,
    canonical_model_trace_entry_digest,
    canonical_model_trace_request_digest,
)


EVIDENCE_ROOT = Path("/data/wenwu.meng/adcraft-evidence")
logger = logging.getLogger(__name__)
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "agent_model_replay"


class AgentModelTraceSessionError(RuntimeError):
    """A safe, bounded trace session failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentModelReplayFixturePlan:
    """Validated immutable output proposed before any fixture write."""

    source_path: Path
    output_path: Path
    source_bundle_digest: str
    fixture: AgentModelTraceBundleV1


@dataclass(frozen=True, slots=True)
class AgentModelReplayFixtureReceipt:
    """Bounded result of one reviewed atomic fixture write."""

    output_path: Path
    source_bundle_digest: str
    fixture_digest: str


class AgentModelReplayFixtureExtractor:
    """Validate and minimize one sealed bundle into a committed replay fixture."""

    _FIXTURE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")

    def __init__(
        self,
        *,
        source_bundle: Path,
        expected_source_digest: str,
        fixture_id: str,
        output_root: Path,
        trusted_source_roots: Sequence[Path] = (EVIDENCE_ROOT, FIXTURE_ROOT),
    ) -> None:
        if not self._FIXTURE_ID_PATTERN.fullmatch(fixture_id):
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        self._source_bundle = source_bundle
        self._expected_source_digest = expected_source_digest
        self._fixture_id = fixture_id
        self._output_root = output_root
        self._trusted_source_roots = tuple(trusted_source_roots)

    def dry_run(self) -> AgentModelReplayFixturePlan:
        """Validate source, safety, output ownership, and digest without writing."""

        replay = AgentModelTraceSessionService.load_replay(
            session_id=f"fixture-extract-{self._fixture_id}",
            bundle_path=self._source_bundle,
            expected_bundle_digest=self._expected_source_digest,
            trusted_roots=self._trusted_source_roots,
        )
        source = AgentModelTraceBundleV1.model_validate_json(
            replay.bundle_path.read_text(encoding="utf-8")
        )
        output_path = self._validated_output_path()
        if output_path.exists():
            raise AgentModelTraceSessionError("acceptance_model_fixture_conflict")
        payload = source.model_dump(mode="json")
        payload.update(
            {
                "fixture_id": self._fixture_id,
                "source_bundle_digest": source.bundle_digest,
                "bundle_digest": f"sha256:{'0' * 64}",
            }
        )
        payload["bundle_digest"] = canonical_model_trace_bundle_digest(payload)
        try:
            fixture = AgentModelTraceBundleV1.model_validate(payload)
        except Exception as error:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid") from error
        return AgentModelReplayFixturePlan(
            source_path=replay.bundle_path,
            output_path=output_path,
            source_bundle_digest=source.bundle_digest,
            fixture=fixture,
        )

    def write(
        self,
        plan: AgentModelReplayFixturePlan,
    ) -> AgentModelReplayFixtureReceipt:
        """Revalidate the source and atomically write exactly the reviewed plan."""

        current = self.dry_run()
        if current != plan:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        _atomic_write_json(plan.output_path, plan.fixture.model_dump(mode="json"))
        return AgentModelReplayFixtureReceipt(
            output_path=plan.output_path,
            source_bundle_digest=plan.source_bundle_digest,
            fixture_digest=plan.fixture.bundle_digest,
        )

    def _validated_output_path(self) -> Path:
        root = self._output_root.expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        for parent in (root, *root.parents):
            if parent.exists() and parent.is_symlink():
                raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        resolved_root = root.resolve(strict=False)
        output_path = (resolved_root / f"{self._fixture_id}.json").resolve(strict=False)
        try:
            output_path.relative_to(resolved_root)
        except ValueError as error:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid") from error
        if output_path.parent != resolved_root or output_path.is_symlink():
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        return output_path


def agent_model_trace_session_from_environment(
    environment: Mapping[str, str] | None = None,
) -> "AgentModelTraceSessionService | None":
    """Build one isolated Python trace session without exposing its path to Pi."""

    values = environment if environment is not None else os.environ
    mode = values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_MODE")
    if mode is None:
        return None
    if values.get("ADCRAFT_ACCEPTANCE_ISOLATED") != "1":
        raise AgentModelTraceSessionError("acceptance_model_replay_forbidden")
    if mode not in {"live_record", "replay"}:
        raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
    required = {
        key: values.get(key)
        for key in (
            "ADCRAFT_ACCEPTANCE_MODEL_TRACE_SESSION_ID",
            "ADCRAFT_ACCEPTANCE_MODEL_TRACE_BUNDLE",
            "ADCRAFT_ACCEPTANCE_MODEL_TRACE_ROOT",
        )
    }
    if not all(required.values()):
        raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
    session_id = str(required["ADCRAFT_ACCEPTANCE_MODEL_TRACE_SESSION_ID"])
    bundle_path = Path(str(required["ADCRAFT_ACCEPTANCE_MODEL_TRACE_BUNDLE"]))
    trusted_root = Path(str(required["ADCRAFT_ACCEPTANCE_MODEL_TRACE_ROOT"])).resolve()
    if mode == "replay":
        expected_digest = values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_EXPECTED_DIGEST")
        if expected_digest is None:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        return AgentModelTraceSessionService.load_replay(
            session_id=session_id,
            bundle_path=bundle_path,
            expected_bundle_digest=expected_digest,
            trusted_roots=(trusted_root,),
        )
    profile_id = values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_PROFILE_ID")
    run_id = values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_RUN_ID")
    if not profile_id or not run_id:
        raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
    return AgentModelTraceSessionService.create_live_record(
        session_id=session_id,
        bundle_path=bundle_path,
        trusted_roots=(trusted_root,),
        fixture_id=values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_FIXTURE_ID")
        or "acceptance-live-record",
        profile_id=profile_id,
        source_acceptance_run_id=run_id,
        source_attempt_id=run_id,
        source_workflow_id=values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_WORKFLOW_ID"),
        source_project_id=values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_PROJECT_ID"),
        parent_bundle_digest=values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_PARENT_DIGEST"),
    )


def isolated_agent_model_replay_enabled(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return true only for the explicit isolated acceptance replay environment."""

    values = environment if environment is not None else os.environ
    return (
        values.get("ADCRAFT_ACCEPTANCE_ISOLATED") == "1"
        and values.get("ADCRAFT_ACCEPTANCE_MODEL_TRACE_MODE") == "replay"
    )


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

    @property
    def replay_bundle(self) -> AgentModelTraceBundleV1 | None:
        """Expose the already validated immutable bundle to isolated startup policy."""

        return self._bundle if self.mode == "replay" else None

    def seal_session(
        self,
        request: AgentModelTraceSealRequestV1,
    ) -> AgentModelTraceSealReceiptV1:
        """Seal one handled live attempt and return bounded report evidence."""

        if request.session_id != self.session_id:
            raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
        with self._lock:
            replayed = self._sealed is not None
            bundle = self.seal(
                terminal_disposition=request.terminal_disposition,
                terminal_failure_code=request.terminal_failure_code,
            )
            return AgentModelTraceSealReceiptV1(
                session_id=self.session_id,
                entry_count=len(bundle.entries),
                bundle_digest=bundle.bundle_digest,
                replayed=replayed,
            )

    def session_status(self) -> AgentModelTraceSessionStatusV1:
        """Return bounded consumption counters without response content or paths."""

        with self._lock:
            entry_count = (
                len(self._bundle.entries) if self._bundle is not None else len(self._entries)
            )
            return AgentModelTraceSessionStatusV1(
                session_id=self.session_id,
                mode=self.mode,
                sealed=self._sealed is not None or self._bundle is not None,
                entry_count=entry_count,
                consumed_entries=self.consumed_count if self.mode == "replay" else 0,
                unused_entries=self.unused_count if self.mode == "replay" else 0,
                bundle_digest=self.bundle_digest,
            )

    def replay_transport_source(
        self,
        *,
        operation: str,
        model_policy_id: str,
        model_ref: str,
    ) -> AgentRuntimeAcceptanceReplaySourceV1:
        """Return the frozen provider identity without consuming replay state."""

        with self._lock:
            if self.mode != "replay" or self._bundle is None:
                raise AgentModelTraceSessionError("acceptance_model_replay_forbidden")
            if self._cursor >= len(self._bundle.entries):
                raise AgentModelTraceSessionError("acceptance_model_replay_miss")
            identity = self._bundle.entries[self._cursor].request_identity
            if (
                identity.operation != operation
                or identity.operation_policy_id != model_policy_id
                or identity.model_ref != model_ref
            ):
                raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
            return AgentRuntimeAcceptanceReplaySourceV1(
                provider=identity.provider,
                model_ref=identity.model_ref,
                model_id=identity.model_id,
                model_policy_id=identity.operation_policy_id,
                supports_tool_calls=identity.supports_tool_calls,
                supports_strict_structured_output=(identity.supports_strict_structured_output),
                supports_streaming=identity.supports_streaming,
                supports_streamed_tool_calls=identity.supports_streamed_tool_calls,
                supports_reasoning_controls=identity.supports_reasoning_controls,
                adapter_id=identity.adapter_id,
                transport_kind=identity.transport_kind,
                capability_revision=identity.capability_revision,
                adapter_revision=identity.adapter_revision,
                gateway_id=identity.gateway_id,
                model_alias=identity.model_alias,
                projection_digest=identity.projection_digest,
                openrouter_routing=identity.openrouter_routing,
                execution_policy=identity.execution_policy,
                trace_session_id=self.session_id,
                expected_bundle_digest=self._bundle.bundle_digest,
            )

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
                "previous_entry_digest": (
                    self._entries[-1].entry_digest if self._entries else None
                ),
                "attempt_id": request.attempt_id,
                "recorded_agent_run_id": request.recorded_agent_run_id,
                "request_identity": request.request_identity,
                "response": request.response,
                "request_snapshot_digest": (
                    request.request_snapshot.digest if request.request_snapshot else None
                ),
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
            if request.request_snapshot is not None:
                request.request_snapshot.validate_identity(request.request_identity)
                path = self._snapshot_path(request.request_snapshot.digest, must_exist=False)
                if path.exists():
                    if (
                        path.read_text()
                        != json.dumps(
                            request.request_snapshot.model_dump(mode="json"),
                            ensure_ascii=True,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n"
                    ):
                        raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
                else:
                    _atomic_write_json(path, request.request_snapshot.model_dump(mode="json"))
            # An unreferenced protected snapshot after a failed write is audit-only.
            # Publish the response receipt/cursor only after durable entry publication.
            self._write_partial(entries=(*self._entries, entry))
            self._entries.append(entry)
            self._record_receipts[request.attempt_id] = receipt
            self._record_request_digests[request.attempt_id] = request_digest
            return receipt

    def _snapshot_path(self, digest: str, *, must_exist: bool) -> Path:
        return validate_agent_model_trace_path(
            self.bundle_path.parent / "request-snapshots" / f"{digest[7:]}.json",
            trusted_roots=self._trusted_roots,
            must_exist=must_exist,
        )

    def load_request_snapshot(self, *, sequence_no: int) -> AgentModelTraceRequestSnapshotV1:
        """Reconstruct only an exact sealed operation; never infer current Workflow state."""

        with self._lock:
            bundle = self._bundle or self._sealed
            if bundle is None or not 1 <= sequence_no <= len(bundle.entries):
                raise AgentModelTraceSessionError("acceptance_model_trace_invalid")
            entry = bundle.entries[sequence_no - 1]
            if entry.request_snapshot_digest is None:
                raise AgentModelTraceSessionError("acceptance_model_request_snapshot_missing")
            path = self._snapshot_path(entry.request_snapshot_digest, must_exist=True)
            try:
                if path.stat().st_size > 2_097_152:
                    raise ValueError("acceptance_model_trace_unsafe")
                snapshot = AgentModelTraceRequestSnapshotV1.model_validate_json(path.read_text())
                if snapshot.digest != entry.request_snapshot_digest:
                    raise ValueError("acceptance_model_trace_invalid")
                snapshot.validate_identity(entry.request_identity)
                return snapshot
            except (ValueError, OSError) as error:
                raise AgentModelTraceSessionError("acceptance_model_trace_invalid") from error

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
                differing_fields = sorted(
                    field
                    for field in type(entry.request_identity).model_fields
                    if getattr(entry.request_identity, field)
                    != getattr(request.request_identity, field)
                )
                logger.warning(
                    "acceptance_model_replay_mismatch sequence=%s differing_fields=%s",
                    entry.sequence_no,
                    ",".join(differing_fields),
                )
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

    def _write_partial(self, *, entries: Sequence[AgentModelTraceEntryV1] | None = None) -> None:
        payload = {
            **self._bundle_metadata,
            "entries": [
                entry.model_dump(mode="json")
                for entry in (entries if entries is not None else self._entries)
            ],
            "sealed": False,
        }
        _atomic_write_json(self.bundle_path.with_suffix(".partial.json"), payload)


def _record_request_digest(request: AgentModelTraceRecordRequestV1) -> str:
    payload = request.model_dump(mode="json", exclude={"session_id"})
    return (
        canonical_model_trace_request_digest(request.request_identity) + ":" + _json_digest(payload)
    )


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
