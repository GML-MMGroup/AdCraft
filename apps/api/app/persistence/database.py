"""Side-effect-free construction of the V2 SQLite runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def resolve_v2_database_path(data_dir: Path) -> Path:
    """Return the canonical V2 SQLite database location without creating it."""

    return data_dir / "v2" / "adcraft.sqlite3"


@dataclass(frozen=True)
class V2Database:
    """Owns the engine and session factory for one V2 SQLite database."""

    engine: Engine
    session_factory: sessionmaker[Session]

    def dispose(self) -> None:
        """Release pooled database resources."""

        self.engine.dispose()


def create_v2_database(data_dir: Path) -> V2Database:
    """Construct the V2 SQLite runtime without opening a connection or creating files."""

    database_path = resolve_v2_database_path(data_dir)
    sqlite_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=NullPool,
    )

    @event.listens_for(sqlite_engine, "connect")
    def configure_sqlite_connection(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=DELETE")
        finally:
            cursor.close()

    return V2Database(
        engine=sqlite_engine,
        session_factory=sessionmaker(
            bind=sqlite_engine,
            class_=Session,
            expire_on_commit=False,
        ),
    )
