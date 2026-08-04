"""Deterministic compatibility identity for the local Pi runtime."""

from pathlib import Path

from app.schemas.agent_runtime import AgentRuntimeManifest


class V2AgentRuntimeManifestService:
    """Load the checked-in generated manifest as the compatibility authority."""

    def __init__(self, manifest_path: Path | None = None) -> None:
        self._manifest_path = manifest_path or (
            Path(__file__).resolve().parents[2]
            / "agent"
            / "src"
            / "generated"
            / "runtime-manifest.json"
        )

    def expected(self) -> AgentRuntimeManifest:
        return AgentRuntimeManifest.model_validate_json(
            self._manifest_path.read_text(encoding="utf-8")
        )
