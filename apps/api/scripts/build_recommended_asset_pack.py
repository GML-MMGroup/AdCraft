"""Build one deterministic, immutable Recommended Assets release package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.v2_recommended_catalog import (
    CatalogBuildMetadataV1,
    CatalogEntityV1,
    CatalogLicenseEntryV1,
    CatalogLicenseManifestV1,
    CatalogManifestV1,
    CatalogMediaDeclarationV1,
    CatalogMemberV1,
)


_CHARACTER_PATTERN = re.compile(r"^character-([0-9]{3})-three-view\.png$")
_SCENE_PATTERN = re.compile(r"^scene-([0-9]{3})-multi-view\.png$")


@dataclass(frozen=True, slots=True)
class BuildOptions:
    source_root: Path
    staging_root: Path
    runtime_root: Path
    dist_dir: Path
    catalog_version: str
    expected_character_count: int
    expected_scene_count: int


@dataclass(frozen=True, slots=True)
class BuildReport:
    runtime_root: Path
    manifest_path: Path
    zip_path: Path
    checksum_path: Path
    release_notes_path: Path
    manifest_sha256: str
    zip_sha256: str
    entity_count: int
    member_count: int
    preview_count: int


def build_recommended_asset_pack(options: BuildOptions) -> BuildReport:
    """Build, publish, and archive one complete catalog snapshot."""

    _validate_options(options)
    if options.staging_root.exists():
        shutil.rmtree(options.staging_root)
    options.staging_root.mkdir(parents=True)

    entities = _build_entities(options)
    manifest = CatalogManifestV1(
        schema_version=1,
        catalog_key="adcraft-recommended-assets-v1",
        catalog_version=options.catalog_version,
        display_name="AdCraft Recommended Assets",
        license_manifest_path="LICENSES.json",
        source_url="",
        build=CatalogBuildMetadataV1(
            builder="adcraft-recommended-assets-builder",
            pillow_version=_pillow_version(),
            character_count=options.expected_character_count,
            scene_count=options.expected_scene_count,
        ),
        entities=tuple(entities),
    )
    licenses = CatalogLicenseManifestV1(
        schema_version=1,
        licenses=(
            CatalogLicenseEntryV1(
                license_id="CC0-1.0",
                name="CC0 1.0 Universal",
                canonical_url="https://creativecommons.org/publicdomain/zero/1.0/",
                attribution_required=False,
                attribution="",
                source_statement="The packaged Recommended Assets source files are released under CC0 1.0.",
            ),
        ),
    )
    manifest_path = options.staging_root / "catalog.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    _write_json(options.staging_root / "LICENSES.json", licenses.model_dump(mode="json"))
    CatalogManifestV1.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    CatalogLicenseManifestV1.model_validate_json(
        (options.staging_root / "LICENSES.json").read_text(encoding="utf-8")
    )

    _publish_runtime_directory(options.staging_root, options.runtime_root)
    options.dist_dir.mkdir(parents=True, exist_ok=True)
    filename = f"adcraft-recommended-assets-v{options.catalog_version}.zip"
    zip_path = options.dist_dir / filename
    _write_deterministic_zip(options.staging_root, zip_path)
    zip_sha256 = _sha256_file(zip_path)
    checksum_path = options.dist_dir / f"{filename}.sha256"
    checksum_path.write_text(f"{zip_sha256}  {filename}\n", encoding="utf-8")
    release_notes_path = (
        options.dist_dir / f"adcraft-recommended-assets-v{options.catalog_version}-release-notes.md"
    )
    release_notes_path.write_text(
        "\n".join(
            (
                f"# AdCraft Recommended Assets v{options.catalog_version}",
                "",
                f"Contains {len(entities)} entities and {len(entities)} original members with JPEG previews.",
                "License: CC0-1.0.",
                "Extract the ZIP below data/assets/catalogs/recommended/.",
                "Verify with: sha256sum -c adcraft-recommended-assets-v"
                f"{options.catalog_version}.zip.sha256",
                "",
            )
        ),
        encoding="utf-8",
    )
    return BuildReport(
        runtime_root=options.runtime_root,
        manifest_path=manifest_path,
        zip_path=zip_path,
        checksum_path=checksum_path,
        release_notes_path=release_notes_path,
        manifest_sha256=_sha256_file(manifest_path),
        zip_sha256=zip_sha256,
        entity_count=len(entities),
        member_count=len(entities),
        preview_count=len(entities),
    )


def _build_entities(options: BuildOptions) -> list[CatalogEntityV1]:
    entities: list[CatalogEntityV1] = []
    for category, pattern, expected_count, entity_type, semantic_type in (
        (
            "characters",
            _CHARACTER_PATTERN,
            options.expected_character_count,
            "character",
            "character_three_view",
        ),
        ("scenes", _SCENE_PATTERN, options.expected_scene_count, "scene", "scene_multi_view_grid"),
    ):
        files = _inventory(options.source_root / category, pattern, expected_count)
        for ordinal, source_path in files:
            slug = f"{entity_type}-{ordinal:03d}"
            original_relative = Path("originals") / category / source_path.name
            preview_relative = Path("previews") / category / f"{slug}.jpg"
            original_target = options.staging_root / original_relative
            original_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, original_target)
            preview_target = options.staging_root / preview_relative
            preview_target.parent.mkdir(parents=True, exist_ok=True)
            _create_preview(original_target, preview_target)
            entity_id = f"recommended-v1-{slug}"
            asset_id = f"recommended-v1-asset-{slug}"
            member = CatalogMemberV1(
                member_id=f"recommended-v1-member-{slug}",
                asset_id=asset_id,
                version_id=f"recommended-v1-version-{slug}",
                semantic_type=semantic_type,
                is_primary=True,
                is_default_reference=True,
                sort_order=0,
                original=_media_declaration(original_target, original_relative, "image/png"),
                preview=_media_declaration(preview_target, preview_relative, "image/jpeg"),
            )
            entities.append(
                CatalogEntityV1(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    library_category=category,
                    display_name=f"{entity_type.title()} {ordinal:03d}",
                    description="",
                    tags=(entity_type, "recommended"),
                    members=(member,),
                )
            )
    return entities


def _inventory(
    directory: Path, pattern: re.Pattern[str], expected_count: int
) -> list[tuple[int, Path]]:
    if expected_count < 1 or not directory.is_dir():
        raise ValueError("recommended catalog source inventory is invalid")
    items: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        match = pattern.fullmatch(path.name)
        if not path.is_file() or match is None:
            raise ValueError("recommended catalog source contains an unexpected file")
        items.append((int(match.group(1)), path))
    items.sort()
    if [ordinal for ordinal, _ in items] != list(range(1, expected_count + 1)):
        raise ValueError("recommended catalog source ordinals are incomplete")
    return items


def _create_preview(original: Path, preview: Path) -> None:
    from PIL import Image, ImageOps

    with Image.open(original) as image:
        rendered = ImageOps.exif_transpose(image).convert("RGB")
        rendered.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        rendered.save(preview, format="JPEG", quality=85, optimize=True, progressive=False)


def _media_declaration(
    path: Path, relative_path: Path, mime_type: str
) -> CatalogMediaDeclarationV1:
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    return CatalogMediaDeclarationV1(
        path=relative_path.as_posix(),
        sha256=_sha256_file(path),
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        width=width,
        height=height,
    )


def _pillow_version() -> str:
    try:
        from PIL import __version__
    except ImportError as error:
        raise RuntimeError(
            "Pillow 11.3.0 is required; run this builder with uv run --with pillow==11.3.0."
        ) from error
    return __version__


def _publish_runtime_directory(staging_root: Path, runtime_root: Path) -> None:
    if runtime_root.exists():
        existing_manifest = runtime_root / "catalog.json"
        if not existing_manifest.is_file() or _sha256_file(existing_manifest) != _sha256_file(
            staging_root / "catalog.json"
        ):
            raise ValueError("recommended catalog runtime version already has different content")
        return
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging_root, runtime_root)


def _write_deterministic_zip(staging_root: Path, zip_path: Path) -> None:
    with ZipFile(zip_path, "w", compression=ZIP_STORED) as archive:
        for path in sorted(item for item in staging_root.rglob("*") if item.is_file()):
            relative = path.relative_to(staging_root).as_posix()
            info = ZipInfo(f"{staging_root.name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_options(options: BuildOptions) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", options.catalog_version):
        raise ValueError("catalog version must use major.minor.patch")
    if options.runtime_root.name != f"v{options.catalog_version}":
        raise ValueError("recommended catalog runtime directory must match the catalog version")


def _parse_args() -> BuildOptions:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--catalog-version", required=True)
    parser.add_argument("--expected-characters", type=int, required=True)
    parser.add_argument("--expected-scenes", type=int, required=True)
    args = parser.parse_args()
    return BuildOptions(
        source_root=args.source_root,
        staging_root=args.staging_root,
        runtime_root=args.runtime_root,
        dist_dir=args.dist_dir,
        catalog_version=args.catalog_version,
        expected_character_count=args.expected_characters,
        expected_scene_count=args.expected_scenes,
    )


if __name__ == "__main__":
    print(build_recommended_asset_pack(_parse_args()))
