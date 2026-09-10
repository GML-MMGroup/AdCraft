import { expect, test } from "@playwright/test";

test("submits the typed reference_source checkpoint against a real workflow", async ({ page }) => {
  const projectId = process.env.REFERENCE_SOURCE_PROJECT_ID;
  const action = process.env.REFERENCE_SOURCE_ACTION === "skip" ? "skip" : "use";
  test.skip(!projectId, "Set REFERENCE_SOURCE_PROJECT_ID for a live V2 reference_source run.");

  const submitRequests: Array<{ url: string; body: unknown }> = [];
  const generationRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/chat/interactions/") && request.url().endsWith("/submit")) {
      submitRequests.push({ url: request.url(), body: request.postDataJSON() });
    }
    if (request.method() === "POST" && /\/(run|generate|variations)\b/i.test(request.url())) {
      generationRequests.push(request.url());
    }
  });

  await page.goto(`/workflow/${encodeURIComponent(projectId!)}`, { waitUntil: "networkidle" });
  const dock = page.locator(".agent-chat__decision-dock").filter({ hasText: /reference/i }).first();
  await expect(dock).toBeVisible();

  if (action === "use") {
    const asset = dock.getByRole("button", { name: /^Select / }).first();
    await expect(asset).toBeVisible();
    await asset.click();
    await dock.getByRole("button", { name: /use reference/i }).click();
  } else {
    await dock.getByRole("button", { name: /skip reference/i }).click();
  }

  await expect.poll(() => submitRequests.length).toBe(1);
  const body = submitRequests[0]?.body as Record<string, unknown>;
  expect(body.submission_kind).toBe("reference_source");
  expect(body.action).toBe(action === "use" ? "use_reference" : "skip_reference");
  expect(body.expected_interaction_revision).toEqual(expect.any(Number));
  expect(body.expected_session_revision).toEqual(expect.any(Number));
  if (action === "use") {
    expect(body.asset_id).toEqual(expect.any(String));
    expect(body.asset_version_id).toEqual(expect.any(String));
  } else {
    expect(body).not.toHaveProperty("asset_id");
    expect(body).not.toHaveProperty("asset_version_id");
  }
  expect(generationRequests).toEqual([]);
});
