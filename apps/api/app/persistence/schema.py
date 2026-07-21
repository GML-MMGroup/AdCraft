"""Programmatic Alembic schema bootstrap for V2 persistence."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI_PATH = _REPOSITORY_ROOT / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = _REPOSITORY_ROOT / "alembic"


def _alembic_config(database: V2Database) -> Config:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option(
        "sqlalchemy.url",
        database.engine.url.render_as_string(hide_password=False),
    )
    return config


def _schema_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_persistence_schema_failed",
        "V2 persistence schema bootstrap failed.",
        stage="schema",
    )


def upgrade_v2_schema(database: V2Database) -> str:
    """Upgrade an explicit V2 database to the Alembic head revision."""

    try:
        command.upgrade(_alembic_config(database), "head")
        revision = current_v2_schema_revision(database)
    except V2PersistenceError:
        raise
    except Exception as error:
        raise _schema_error() from error

    if revision is None:
        raise _schema_error()
    return revision


def current_v2_schema_revision(database: V2Database) -> str | None:
    """Return the current Alembic revision for an explicit V2 database."""

    try:
        with database.engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return None
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except Exception as error:
        raise _schema_error() from error
