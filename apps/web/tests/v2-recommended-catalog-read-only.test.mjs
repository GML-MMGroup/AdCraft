import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = (path) => fs.readFileSync(new URL(path, root), "utf8");

test("Recommended Assets discovery is read-only and polls only indexing", () => {
  const hook = read("src/features/assets/useRecommendedCatalog.ts");
  const client = read("src/api/v2Client.ts");
  const page = read("src/pages/AssetsPage.tsx");
  const picker = read("src/features/workflow/v2/slots/V2AssetReferencePicker.tsx");

  assert.doesNotMatch(hook, /installRecommendedCatalog/);
  assert.doesNotMatch(client, /installRecommendedCatalog/);
  assert.doesNotMatch(page, /catalog\.install/);
  assert.doesNotMatch(picker, /catalog\.install/);
  assert.match(hook, /status\.status !== "indexing"/);
});
