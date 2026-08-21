"""Grace-period cleanup for unreferenced content-addressed media objects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.persistence.asset_library_repository import V2AssetLibraryRepository


class AgentCanvasOrphanObjectCleanup:
    """Delete only old content objects that have no immutable Asset version."""

    def __init__(
        self,
        data_dir: Path,
        assets: V2AssetLibraryRepository,
        *,
        grace_period: timedelta = timedelta(hours=24),
    ) -> None:
        self._data_dir = data_dir
        self._assets = assets
        self._grace_period = grace_period

    def run(self, *, now: datetime | None = None) -> tuple[str, ...]:
        timestamp = _utc(now or datetime.now(timezone.utc))
        cutoff = timestamp - self._grace_period
        root = self._data_dir / "assets" / "objects" / "sha256"
        if not root.is_dir():
            return ()
        removed: list[str] = []
        for path in sorted(root.glob("*/*/*")):
            if not path.is_file() or path.is_symlink():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified >= cutoff:
                continue
            storage_key = path.relative_to(self._data_dir).as_posix()
            if self._assets.count_versions_with_storage_key(storage_key) != 0:
                continue
            path.unlink(missing_ok=True)
            removed.append(storage_key)
        return tuple(removed)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
