from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _GraphRunState:
    selected: set[str]
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    waiting: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)
    running_node_ids: set[str] = field(default_factory=set)
    skipped_reasons: dict[str, str] = field(default_factory=dict)
    executed_nodes: list[str] = field(default_factory=list)
    completed_nodes: list[str] = field(default_factory=list)
    skipped_nodes: list[str] = field(default_factory=list)
    stale_nodes: list[str] = field(default_factory=list)
    waiting_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[dict[str, str]] = field(default_factory=list)
    blocked_nodes: list[str] = field(default_factory=list)
    affected_downstream_nodes: list[str] = field(default_factory=list)
