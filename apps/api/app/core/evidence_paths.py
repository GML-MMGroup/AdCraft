from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


ADCRAFT_EVIDENCE_ROOT = Path("/data/wenwu.meng/adcraft-evidence")
_ADCRAFT_HOST_ROOT = ADCRAFT_EVIDENCE_ROOT.parent


def validate_adcraft_evidence_path(
    value: Path,
    *,
    require_unified_root: bool = False,
    leaf_prefix: str | None = None,
) -> Path:
    """Resolve an evidence path and reject retired top-level AdCraft roots."""

    resolved = value.expanduser().resolve()
    if resolved == ADCRAFT_EVIDENCE_ROOT or resolved.is_relative_to(ADCRAFT_EVIDENCE_ROOT):
        if leaf_prefix is not None:
            relative = resolved.relative_to(ADCRAFT_EVIDENCE_ROOT)
            if not relative.parts or not relative.parts[0].startswith(leaf_prefix):
                raise ValueError("adcraft_evidence_path_outside_root")
        return resolved

    if resolved.is_relative_to(_ADCRAFT_HOST_ROOT):
        relative = resolved.relative_to(_ADCRAFT_HOST_ROOT)
        if relative.parts and relative.parts[0].startswith("adcraft-"):
            raise ValueError("adcraft_evidence_path_outside_root")
    if require_unified_root:
        raise ValueError("adcraft_evidence_path_outside_root")
    return resolved


def new_adcraft_evidence_directory(prefix: str) -> Path:
    """Return a timestamped leaf under the canonical evidence root."""

    if not prefix.startswith("adcraft-") or "/" in prefix or ".." in prefix:
        raise ValueError("adcraft_evidence_prefix_invalid")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ADCRAFT_EVIDENCE_ROOT / f"{prefix}-{stamp}"
