"""Read-only checks for a local installation before maintenance."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3

from app.persistence.database import resolve_v2_database_path
from app.persistence.schema import v2_schema_head_revision


_ACTIVE_STATES = {
    "agent_canvas_executions": ("queued", "running", "waiting"),
    "agent_canvas_provider_tasks": ("submitted", "waiting", "recovering"),
    "agent_canvas_editing_exports": ("queued", "exporting"),
    "agent_runs": ("queued", "running"),
    "agent_canvas_continuation_outbox": ("queued", "leased", "retry_wait"),
    "agent_canvas_prompt_preparation_outbox": ("queued", "leased"),
    "brand_continuations": ("queued", "running"),
    "brand_form_generation_leases": ("generating",),
    "agent_canvas_post_ready_effects": ("queued", "running"),
}
_ACTIVE_STATE_COLUMNS = {
    "agent_canvas_automatic_run_commands": ("pending", "claimed"),
    "agent_canvas_result_publication_intents": ("preparing", "prepared"),
}


def inspect_local_installation(data_dir: Path) -> dict[str, object]:
    """Inspect without initializing a database, loading credentials, or starting workers."""

    path = resolve_v2_database_path(data_dir)
    report: dict[str, object] = {
        "database_exists": path.is_file(),
        "schema_revision": None,
        "target_revision": v2_schema_head_revision(),
        "integrity": "not_initialized",
        "idle": True,
        "active_records": {},
        "tools": {name: shutil.which(name) is not None for name in ("node", "ffmpeg", "ffprobe")},
    }
    if not path.is_file():
        return report
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        report["integrity"] = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "alembic_version" in tables:
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            report["schema_revision"] = str(revision[0]) if revision else None
        active = {}
        for table, states in {**_ACTIVE_STATES, **_ACTIVE_STATE_COLUMNS}.items():
            if table not in tables:
                continue
            placeholders = ",".join("?" for _ in states)
            column = "state" if table in _ACTIVE_STATE_COLUMNS else "status"
            # Table names come exclusively from the fixed local registry above.
            active[table] = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({placeholders})", states
                ).fetchone()[0]
            )
        report["active_records"] = active
        report["idle"] = not any(active.values())
    return report
