from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas.workflow_v2_production_acceptance import V2ProductionAcceptanceFixture


DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "v2-production-acceptance"
DEFAULT_ALLOWLIST = ("core_av_canary", "chat_planning_canary")


class V2ProductionAcceptanceFixtureRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class V2ProductionAcceptanceFixtureBundle:
    fixture: V2ProductionAcceptanceFixture
    fixture_dir: Path
    asset_paths: dict[str, Path]


class V2ProductionAcceptanceFixtureRegistry:
    def __init__(
        self,
        fixture_root: Path | None = None,
        *,
        allowlisted_directories: tuple[str, ...] = DEFAULT_ALLOWLIST,
    ) -> None:
        self._fixture_root = (fixture_root or DEFAULT_FIXTURE_ROOT).resolve()
        self._allowlisted_directories = tuple(allowlisted_directories)

    def list_fixtures(self) -> list[V2ProductionAcceptanceFixture]:
        fixtures: list[V2ProductionAcceptanceFixture] = []
        seen: set[str] = set()
        for directory in self._allowlisted_directories:
            bundle = self._load_directory(directory)
            if bundle.fixture.fixture_id in seen:
                raise self._invalid("Duplicate fixture id in the production acceptance allowlist.")
            seen.add(bundle.fixture.fixture_id)
            fixtures.append(bundle.fixture)
        return fixtures

    def load(self, fixture_id: str) -> V2ProductionAcceptanceFixtureBundle:
        if fixture_id not in self._allowlisted_directories:
            raise V2ProductionAcceptanceFixtureRegistryError(
                "production_acceptance_fixture_not_found",
                "Production acceptance fixture was not found.",
            )
        bundle = self._load_directory(fixture_id)
        if bundle.fixture.fixture_id != fixture_id:
            raise self._invalid("Fixture id does not match its allowlisted directory.")
        return bundle

    def _load_directory(self, directory: str) -> V2ProductionAcceptanceFixtureBundle:
        fixture_dir = (self._fixture_root / directory).resolve()
        if not _is_within(fixture_dir, self._fixture_root):
            raise self._invalid("Fixture directory escapes the configured fixture root.")
        definition_path = fixture_dir / "fixture.json"
        try:
            payload = json.loads(definition_path.read_text(encoding="utf-8"))
            fixture = V2ProductionAcceptanceFixture.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise self._invalid("Production acceptance fixture definition is invalid.") from exc

        asset_paths: dict[str, Path] = {}
        for asset in fixture.input_assets:
            relative = Path(asset.relative_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise self._invalid("Fixture asset path escapes the fixture directory.")
            candidate = fixture_dir / relative
            resolved = candidate.resolve(strict=False)
            if not _is_within(resolved, fixture_dir):
                raise self._invalid("Fixture asset path escapes the fixture directory.")
            asset_paths[asset.relative_path] = candidate

        return V2ProductionAcceptanceFixtureBundle(
            fixture=fixture,
            fixture_dir=fixture_dir,
            asset_paths=asset_paths,
        )

    @staticmethod
    def _invalid(message: str) -> V2ProductionAcceptanceFixtureRegistryError:
        return V2ProductionAcceptanceFixtureRegistryError(
            "production_acceptance_fixture_invalid",
            message,
        )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
