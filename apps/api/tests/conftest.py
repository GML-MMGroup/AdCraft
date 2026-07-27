from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.database import create_v2_database
from app.persistence.schema import upgrade_v2_schema


@pytest.fixture
def v2_media_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    database = create_v2_database(data_dir)
    try:
        upgrade_v2_schema(database)
    finally:
        database.dispose()
    return data_dir
