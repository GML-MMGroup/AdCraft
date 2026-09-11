"""Cross-process file locking helpers that work on both POSIX and Windows.

The upstream code uses ``fcntl.flock`` which only exists on Unix. This module
provides equivalent exclusive-lock/unlock helpers backed by ``msvcrt.locking``
on Windows so the API server can run natively without Docker.
"""

from __future__ import annotations

import sys
from typing import BinaryIO, TextIO

if sys.platform == "win32":  # pragma: no cover - platform specific
    import msvcrt

    _LOCK_REGION_BYTES = 1

    def lock_exclusive(handle: BinaryIO | TextIO) -> None:
        """Acquire an exclusive cross-process lock on the handle."""
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, _LOCK_REGION_BYTES)

    def unlock(handle: BinaryIO | TextIO) -> None:
        """Release the exclusive cross-process lock on the handle."""
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_REGION_BYTES)

else:
    import fcntl

    def lock_exclusive(handle: BinaryIO | TextIO) -> None:
        """Acquire an exclusive cross-process lock on the handle."""
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def unlock(handle: BinaryIO | TextIO) -> None:
        """Release the exclusive cross-process lock on the handle."""
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
