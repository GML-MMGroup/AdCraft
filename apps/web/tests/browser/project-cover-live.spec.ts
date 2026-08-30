import { expect, test } from "@playwright/test";

test("loads a version-pinned project cover without a per-project assets request", async ({ page }) => {
  const projectName = process.env.PROJECT_COVER_PROJECT_NAME;
  test.skip(!projectName, "Set PROJECT_COVER_PROJECT_NAME for a live V2 backend run.");

  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });

  await page.goto("/projects", { waitUntil: "networkidle" });
  const card = page.locator(`[data-project-card="${projectName!.toLowerCase()}"]`);
  await expect(card).toBeVisible();
  await expect(card.locator(".project-preview-image img")).toBeVisible();

  expect(apiRequests.some((url) => /\/api\/v2\/workflows\/[^/]+\/assets/.test(url))).toBe(false);
  const firstPreviewRequestCount = apiRequests.filter((url) => /\/api\/v2\/assets\/[^/]+\/preview\?v=/.test(url)).length;
  expect(firstPreviewRequestCount).toBe(1);

  await page.reload({ waitUntil: "networkidle" });
  await expect(page.locator(`[data-project-card="${projectName!.toLowerCase()}"] .project-preview-image img`)).toBeVisible();
  const reloadPreviewRequestCount = apiRequests.filter((url) => /\/api\/v2\/assets\/[^/]+\/preview\?v=/.test(url)).length;
  expect(reloadPreviewRequestCount).toBeLessThanOrEqual(2);
});
