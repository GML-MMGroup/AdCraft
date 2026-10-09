"""Repair Brand chat history from exact persisted evidence; dry-run by default."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select, text

from app.persistence.brand_answer_history import append_brand_answer_in_transaction
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import create_v2_database
from app.persistence.models import AgentCanvasWorkflowRow, BrandRow


def repair(data_dir: Path, workflow_id: str, *, apply: bool = False) -> int:
    database = create_v2_database(data_dir)
    try:
        repository = BrandDecisionRepository(database)
        with database.engine.connect() as connection:
            brand_id = connection.execute(
                select(BrandRow.brand_id)
                .join(
                    AgentCanvasWorkflowRow, AgentCanvasWorkflowRow.project_id == BrandRow.project_id
                )
                .where(AgentCanvasWorkflowRow.workflow_id == workflow_id)
            ).scalar_one()
        entries = sorted(
            repository.list_decision_log(brand_id), key=lambda e: (e.created_at, e.log_id)
        )
        with database.engine.connect() as connection:
            # Reserve the writer before allocating chat sequences. No scheduling or model calls.
            connection.execute(text("BEGIN IMMEDIATE"))
            count = sum(
                append_brand_answer_in_transaction(connection, brand_id=brand_id, entry=e)
                for e in entries
            )
            if apply:
                connection.commit()
            else:
                connection.rollback()
        return count
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    count = repair(args.data_dir, args.workflow_id, apply=args.apply)
    print(f"{'Restored' if args.apply else 'Would restore'} {count} Brand question/answer pairs.")


if __name__ == "__main__":
    main()
