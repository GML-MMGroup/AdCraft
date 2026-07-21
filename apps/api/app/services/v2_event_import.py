"""Canonical V2 event-history import from workflow-level JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.persistence.event_payload import serialize_event_payload
from app.persistence.event_repository import EventRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_persistence import V2EventMigrationReport, V2EventSourceStats
from app.schemas.workflow_v2 import WorkflowV2Event


V2_EVENT_IMPORT_MIGRATION_NAME = "v2_event_store_import_v1"


class V2EventImportService:
    """Imports only canonical workflow event arrays into the V2 event repository."""

    def __init__(self, data_dir: Path, repository: EventRepository) -> None:
        self._data_dir = data_dir
        self._repository = repository

    def import_if_required(self) -> V2EventMigrationReport:
        """Return an existing completed report or atomically import a validated corpus."""

        completed_report = self._repository.completed_migration_report(
            V2_EVENT_IMPORT_MIGRATION_NAME
        )
        if completed_report is not None:
            return completed_report

        try:
            events, source_stats = self._load_canonical_events()
        except (OSError, TypeError, ValueError, ValidationError, V2PersistenceError) as error:
            raise _import_failed_error() from error
        return self._repository.import_verified_events(
            events,
            source_stats,
            V2_EVENT_IMPORT_MIGRATION_NAME,
        )

    def discover_canonical_event_paths(self) -> list[Path]:
        """Discover only sorted workflow-level canonical event files."""

        runs_dir = self._data_dir / "v2" / "runs"
        if not runs_dir.exists():
            return []
        return sorted(runs_dir.glob("*/events.json"), key=lambda path: path.parent.name)

    def _load_canonical_events(self) -> tuple[list[WorkflowV2Event], dict[str, V2EventSourceStats]]:
        all_events: list[WorkflowV2Event] = []
        source_stats: dict[str, V2EventSourceStats] = {}
        for path in self.discover_canonical_event_paths():
            workflow_id = path.parent.name
            raw_events = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw_events, list):
                raise ValueError("Canonical V2 event source must be a JSON array.")

            events: list[WorkflowV2Event] = []
            previous_seq = 0
            for raw_event in raw_events:
                event = WorkflowV2Event.model_validate(raw_event)
                if event.workflow_id != workflow_id or event.seq <= 0 or event.seq <= previous_seq:
                    raise ValueError(
                        "Canonical V2 event source has invalid workflow identity or sequence."
                    )
                serialize_event_payload(event.payload)
                events.append(event)
                previous_seq = event.seq

            all_events.extend(events)
            source_stats[workflow_id] = V2EventSourceStats(
                workflow_id=workflow_id,
                source_count=len(events),
                max_seq=previous_seq,
            )
        return all_events, source_stats


def _import_failed_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_event_import_failed",
        "V2 event import failed.",
        stage="event_import",
    )
