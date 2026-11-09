"""Generation admission within the same SQLite transaction as a lease claim."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Connection

from app.persistence.models import (
    AgentCanvasExecutionMemberRow as Member,
    AgentCanvasExecutionRow as Execution,
    AgentCanvasNodeLeaseRow as Lease,
    AgentCanvasNodeRow as Node,
)


def has_generation_capacity(
    connection: Connection,
    *,
    execution_id: str,
    node_id: str,
    now: datetime,
    limits: Mapping[str, int],
    total_limit: int,
) -> bool:
    """Count running remote work and unexpired local reservations across projects."""

    target = connection.execute(
        select(Node.node_type, Member.state)
        .join(Member, Member.node_id == Node.node_id)
        .where(Member.execution_id == execution_id, Node.node_id == node_id)
    ).one_or_none()
    if target is None or target.state not in {"queued", "waiting"}:
        return False
    rows = connection.execute(
        select(Node.node_type, func.count())
        .select_from(Member)
        .join(Node, Node.node_id == Member.node_id)
        .join(Execution, Execution.execution_id == Member.execution_id)
        .outerjoin(
            Lease, and_(Lease.execution_id == Member.execution_id, Lease.node_id == Member.node_id)
        )
        .where(
            Execution.status.in_(("queued", "running", "waiting")),
            Member.state.in_(("queued", "waiting", "running")),
            or_(Member.execution_id != execution_id, Member.node_id != node_id),
            or_(
                Member.state == "running",
                and_(Lease.state == "claimed", Lease.expires_at > now.isoformat()),
            ),
        )
        .group_by(Node.node_type)
    )
    usage = {str(node_type): int(count) for node_type, count in rows}
    return sum(usage.values()) < total_limit and usage.get(target.node_type, 0) < limits.get(
        target.node_type, total_limit
    )
