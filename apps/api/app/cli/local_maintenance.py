"""Inspect local tasks and create or verify database recovery snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from app.persistence.backup import create_database_backup, verify_database_backup
from app.persistence.database import resolve_v2_database_path
from app.persistence.errors import V2PersistenceError
from app.services.local_maintenance import inspect_local_installation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "backup"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--require-idle", action="store_true")
    verify = commands.add_parser("verify-backup")
    verify.add_argument("--database", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify-backup":
            report = verify_database_backup(args.database, args.manifest)
            print(report.model_dump_json())
            return 0
        inspection = inspect_local_installation(args.data_dir)
        if args.command == "check":
            print(json.dumps(inspection, sort_keys=True))
            return (
                1
                if inspection["integrity"] not in {"ok", "not_initialized"}
                or (args.require_idle and not inspection["idle"])
                else 0
            )
        if not inspection["idle"]:
            print(
                json.dumps(
                    {
                        "error": "active_work",
                        "message": "Wait for active work to finish before maintenance.",
                        "active_records": inspection["active_records"],
                    }
                )
            )
            return 2
        report = create_database_backup(args.data_dir, resolve_v2_database_path(args.data_dir))
        print(report.model_dump_json())
        return 0
    except (V2PersistenceError, OSError, sqlite3.Error) as error:
        print(
            json.dumps(
                {
                    "error": getattr(error, "code", "local_maintenance_failed"),
                    "message": "Local maintenance could not complete. The original database was not replaced.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
