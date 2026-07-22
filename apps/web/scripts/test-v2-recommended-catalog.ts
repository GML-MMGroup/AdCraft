import assert from "node:assert/strict";

import { normalizeV2AssetLibraryEntityDetail, normalizeV2RecommendedCatalogStatus } from "../src/api/v2Normalizers.ts";
import { v2AssetPreviewUrl } from "../src/features/assets/v2AssetLibraryModel.ts";

const status = normalizeV2RecommendedCatalogStatus({
  catalog_key: "adcraft-recommended-assets-v1",
  catalog_version: "1.0.0",
  status: "ready",
  entity_count: 61,
  member_count: 61,
  manifest_sha256: "a".repeat(64),
  expected_relative_path: "data/assets/catalogs/recommended/",
  message: "Recommended assets are ready.",
});
assert.equal(status.status, "ready");
assert.equal(status.entity_count, 61);

const entity = normalizeV2AssetLibraryEntityDetail({
  entity_id: "recommended-v1-character-001",
  scope: "recommended",
  entity_type: "character",
  library_category: "characters",
  display_name: "Character 001",
  tags: [],
  is_favorite: false,
  member_count: 1,
  preview_url: "/media/assets/catalogs/recommended/v1.0.0/previews/characters/character-001.jpg",
  members: [],
});
assert.match(v2AssetPreviewUrl(entity) ?? "", /previews\/characters/);
