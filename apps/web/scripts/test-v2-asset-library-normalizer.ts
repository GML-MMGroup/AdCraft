import assert from "node:assert/strict";

import { normalizeV2AssetLibraryEntityDetail } from "../src/api/v2Normalizers.ts";

const normalized = normalizeV2AssetLibraryEntityDetail({
  entity_id: "aent_recommended_character",
  scope: "recommended",
  entity_type: "character",
  library_category: "characters",
  display_name: "Recommended Character",
  description: "",
  tags: [],
  is_favorite: false,
  status: "active",
  member_count: 0,
  members: [],
  catalog_source_url: "https://catalog.example.invalid/character",
  license_id: "CC-BY-4.0",
  attribution: "AdCraft catalog contributor",
});

const detail = normalized as typeof normalized & {
  catalog_source_url?: string | null;
  license_id?: string | null;
  attribution?: string | null;
};

assert.equal(detail.catalog_source_url, "https://catalog.example.invalid/character");
assert.equal(detail.license_id, "CC-BY-4.0");
assert.equal(detail.attribution, "AdCraft catalog contributor");
