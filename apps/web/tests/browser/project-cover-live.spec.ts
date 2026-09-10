import { expect, test } from "@playwright/test";

test("loads a version-pinned project cover without a per-project assets request", async ({ page }) => {
  const projectName = process.env.PROJECT_COVER_PROJECT_NAME;
  const projectId = process.env.PROJECT_COVER_PROJECT_ID;
  test.skip(!projectName && !projectId, "Set PROJECT_COVER_PROJECT_NAME or PROJECT_COVER_PROJECT_ID for a live V2 backend run.");

  let targetWorkflowId: string | undefined;
  let targetPreviewPath: string | undefined;
  if (projectId) {
    const response = await page.request.get(`/api/v2/projects/${projectId}`);
    expect(response.ok()).toBe(true);
    const project = await response.json() as { workflow_id?: string };
    targetWorkflowId = project.workflow_id;
    expect(targetWorkflowId).toBeTruthy();
    const listingResponse = await page.request.get("/api/v2/projects?status=active&limit=100");
    expect(listingResponse.ok()).toBe(true);
    const listing = await listingResponse.json() as {
      items?: Array<{ project_id?: string; cover?: { preview_url?: string | null } | null }>;
    };
    targetPreviewPath = listing.items?.find((item) => item.project_id === projectId)?.cover?.preview_url ?? undefined;
    expect(targetPreviewPath).toBeTruthy();
  }

  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });

  await page.goto("/projects", { waitUntil: "networkidle" });
  const card = projectId
    ? page.locator(`[data-project-id="${projectId}"]`)
    : page.locator(`[data-project-card="${projectName!.toLowerCase()}"]`).first();
  await expect(card).toBeVisible();
  await expect(card.locator(".project-preview-image img")).toBeVisible();

  const workflowAssetRequests = apiRequests.filter((url) => /\/api\/v2\/workflows\/[^/]+\/assets/.test(url));
  expect(workflowAssetRequests.some((url) => targetWorkflowId ? url.includes(`/workflows/${targetWorkflowId}/assets`) : true)).toBe(false);
  const firstPreviewRequestCount = apiRequests.filter((url) => targetPreviewPath ? url.includes(targetPreviewPath) : /\/api\/v2\/assets\/[^/]+\/preview\?v=/.test(url)).length;
  expect(firstPreviewRequestCount).toBe(1);

  await page.reload({ waitUntil: "networkidle" });
  const reloadedCard = projectId
    ? page.locator(`[data-project-id="${projectId}"]`)
    : page.locator(`[data-project-card="${projectName!.toLowerCase()}"]`).first();
  await expect(reloadedCard.locator(".project-preview-image img")).toBeVisible();
  const reloadPreviewRequestCount = apiRequests.filter((url) => targetPreviewPath ? url.includes(targetPreviewPath) : /\/api\/v2\/assets\/[^/]+\/preview\?v=/.test(url)).length;
  expect(reloadPreviewRequestCount).toBeLessThanOrEqual(2);
});
