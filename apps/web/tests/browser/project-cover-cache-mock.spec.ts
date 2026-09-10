import { expect, test } from "@playwright/test";

const previewSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240"><rect width="320" height="240" fill="#9dafe6"/></svg>`;

function coverAsset() {
  return {
    asset_id: "cover-asset",
    version_id: "cover-version",
    project_id: "project-cover-cache",
    workflow_id: "workflow-cover-cache",
    media_type: "image",
    source_type: "generated",
    semantic_type: "product",
    display_name: "Product Main",
    mime_type: "image/svg+xml",
    status: "ready",
    size_bytes: previewSvg.length,
    storage_key: null,
    preview_url: "/api/v2/assets/cover-asset/preview",
    media_url: "/api/v2/assets/cover-asset/content",
    width: 320,
    height: 240,
    duration_seconds: null,
    checksum: "cover-checksum",
    source_semantic_role: "product_main",
    source_node_id: null,
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: { source_asset_version_ids: [] },
    quality_metadata: {},
    created_at: "2026-08-30T08:00:00Z",
  };
}

test("reuses cover metadata across virtual priority changes and reloads", async ({ page }) => {
  let assetRequests = 0;
  let renditionRequests = 0;
  const renditionPaths: string[] = [];
  const unexpectedApiRequests: string[] = [];

  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v2/workflows/workflow-cover-cache/assets") {
      assetRequests += 1;
      if (assetRequests > 1) await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ workflow_id: "workflow-cover-cache", assets: [coverAsset()] }),
      });
      return;
    }
    if (url.pathname === "/api/v2/assets/cover-asset/preview" || url.pathname === "/api/v2/assets/cover-asset/content") {
      renditionRequests += 1;
      renditionPaths.push(url.pathname);
      await route.fulfill({ status: 200, contentType: "image/svg+xml", body: previewSvg });
      return;
    }
    unexpectedApiRequests.push(url.pathname);
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ message: "mock route not found" }) });
  });

  await page.goto("/tests/browser/project-cover-cache-mock.html");
  const image = page.locator(".project-preview-image img");
  await expect(image).toBeVisible();
  expect(assetRequests).toBe(1);
  expect(renditionPaths).toContain("/api/v2/assets/cover-asset/preview");

  await page.evaluate(() => window.scrollTo(0, 300));
  await page.waitForTimeout(50);
  expect(assetRequests).toBe(1);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(image).toBeVisible({ timeout: 300 });
  expect(assetRequests).toBe(2);
  expect(renditionRequests).toBeGreaterThan(0);
  expect(unexpectedApiRequests).toEqual([]);
});
