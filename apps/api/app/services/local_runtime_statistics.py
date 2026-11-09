"""Aggregate observed local execution outcomes without provider requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import and_, func, select

from app.persistence.database import V2Database
from app.persistence.models import (
    AgentCanvasExecutionMemberRow as Member,
    WorkflowEventRow as Event,
)
from app.schemas.local_runtime_statistics import LocalModelActivityV1, LocalRuntimeStatisticsV1


@dataclass
class _Activity:
    states: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    durations: list[float] = field(default_factory=list)


class LocalRuntimeStatisticsService:
    """Count one latest member outcome per execution, not billable provider calls."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def summarize(self, *, days: int = 7, now: datetime | None = None) -> LocalRuntimeStatisticsV1:
        if not 1 <= days <= 90:
            raise ValueError("Statistics period must be between 1 and 90 days.")
        now = now or datetime.now(timezone.utc)
        since = (now - timedelta(days=days)).isoformat()
        starts = (
            select(
                Event.execution_id, Event.node_id, func.max(Event.created_at).label("started_at")
            )
            .where(Event.event_type == "node_generation_started", Event.created_at >= since)
            .group_by(Event.execution_id, Event.node_id)
            .subquery()
        )
        with self._database.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        Member.state,
                        Member.prompt_metadata_json,
                        Member.error_json,
                        Member.updated_at,
                        starts.c.started_at,
                    )
                    .outerjoin(
                        starts,
                        and_(
                            starts.c.execution_id == Member.execution_id,
                            starts.c.node_id == Member.node_id,
                        ),
                    )
                    .where(Member.updated_at >= since, Member.updated_at <= now.isoformat())
                    .order_by(Member.updated_at.desc(), Member.member_id)
                    .limit(5001)
                )
                .mappings()
                .all()
            )
        groups: dict[str | None, _Activity] = {}
        for row in rows[:5000]:
            metadata = _object(row["prompt_metadata_json"])
            resolution = metadata.get("model_resolution")
            ref = resolution.get("model_ref") if isinstance(resolution, dict) else None
            ref = ref if isinstance(ref, str) and ref else None
            group = groups.setdefault(ref, _Activity())
            state = str(row["state"])
            group.states[state] = group.states.get(state, 0) + 1
            if state == "failed":
                error = _object(row["error_json"])
                code = error.get("code")
                code = code if isinstance(code, str) and code else "unknown_error"
                group.errors[code] = group.errors.get(code, 0) + 1
            if state == "succeeded" and row["started_at"]:
                duration = _duration(row["started_at"], row["updated_at"])
                if duration is not None:
                    group.durations.append(duration)
        items = []
        for ref, group in sorted(groups.items(), key=lambda item: item[0] or ""):
            succeeded = group.states.get("succeeded", 0)
            failed = group.states.get("failed", 0)
            samples = succeeded + failed
            items.append(
                LocalModelActivityV1(
                    model_ref=ref,
                    succeeded=succeeded,
                    failed=failed,
                    active=sum(
                        group.states.get(state, 0) for state in ("queued", "waiting", "running")
                    ),
                    cancelled=group.states.get("cancelled", 0),
                    blocked=group.states.get("blocked", 0),
                    skipped=group.states.get("skipped_dependency", 0),
                    success_rate=succeeded / samples if samples else None,
                    mean_success_seconds=sum(group.durations) / len(group.durations)
                    if group.durations
                    else None,
                    duration_samples=len(group.durations),
                    error_codes=group.errors,
                )
            )
        return LocalRuntimeStatisticsV1(
            generated_at=now,
            period_days=days,
            sampled_members=min(len(rows), 5000),
            truncated=len(rows) > 5000,
            items=tuple(items),
        )


def _object(raw: str | None) -> dict[str, object]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _duration(start: str, end: str) -> float | None:
    try:
        duration = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        return duration if duration >= 0 else None
    except (TypeError, ValueError):
        return None
