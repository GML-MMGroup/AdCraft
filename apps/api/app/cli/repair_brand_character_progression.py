"""Recover a proven Brand Character scope failure; validate only unless --apply is supplied."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.persistence.brand_character_recovery_repository import BrandCharacterRecoveryRepository
from app.persistence.database import create_v2_database, resolve_v2_database_path
from app.persistence.errors import V2PersistenceError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--failed-turn-id", required=True)
    parser.add_argument("--expected-session-revision", type=int, required=True)
    parser.add_argument("--expected-requirement-revision-id", required=True)
    parser.add_argument("--expected-content-digest", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not resolve_v2_database_path(args.data_dir).is_file():
        parser.error("An existing V2 database is required.")
    database = create_v2_database(args.data_dir)
    try:
        session = BrandCharacterRecoveryRepository(database).recover(
            args.workflow_id,
            failed_turn_id=args.failed_turn_id,
            expected_session_revision=args.expected_session_revision,
            expected_requirement_revision_id=args.expected_requirement_revision_id,
            expected_content_digest=args.expected_content_digest,
            apply=args.apply,
        )
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry_run",
                    "workflow_id": args.workflow_id,
                    "session_revision": session.revision,
                    "stage": session.journey.stage,
                    "work_scheduled": False,
                }
            )
        )
    except V2PersistenceError as error:
        parser.error(f"{error.code}: {error}")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
