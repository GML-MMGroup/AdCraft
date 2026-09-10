import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const cover = readFileSync("public/assets/card1.webp");
const fixtures = [0, 1, 2, 3].map((index) => ({
  project_id: `project-recent-${index}`,
  workflow_id: `workflow-other-${index}`,
  name: index === 3 ? "真实项目超长名称验证文字不超出卡片边界 Long campaign title" : `Real campaign ${index}`,
  status: "active", is_favorite: false, project_version: 1,
  updated_at: `2026-09-0${7 - index}T00:00:00Z`,
  cover_asset_id: index < 2 ? `cover-${index}` : null,
  cover_version_id: index < 2 ? "version-1" : null,
  cover_state: index < 2 ? "ready" : "none", cover_source: null, cover_updated_at: null,
  cover: index < 2 ? {
    asset_id: `cover-${index}`, version_id: "version-1", media_type: index ? "video" : "image",
    preview_url: `/media/recent-preview-${index}.webp?v=version-1`,
    poster_url: index ? "/media/recent-poster-1.webp?v=version-1" : null,
  } : null,
}));

async function mockApi(page: Page, getResponse: () => { status?: number; items?: typeof fixtures } = () => ({ items: fixtures })) {
  const apiRequests: string[] = [];
  const mediaRequests: string[] = [];
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    apiRequests.push(url.pathname + url.search);
    if (url.pathname.endsWith("/health")) return route.fulfill({ json: { service: "AdCraft", mode: "mock" } });
    if (url.pathname === "/api/v2/projects") {
      expect(url.searchParams.get("status")).toBe("active");
      expect(url.searchParams.get("limit")).toBe("4");
      const response = getResponse();
      return route.fulfill({ status: response.status ?? 200, json: { items: response.items ?? [], next_cursor: "do-not-fetch-next-page" }, headers: { ETag: '"recent-four"' } });
    }
    return route.fulfill({ status: 404, json: { detail: "Unexpected workspace request" } });
  });
  await page.route("**/media/recent-*", async (route) => {
    mediaRequests.push(new URL(route.request().url()).pathname);
    await route.fulfill({ body: cover, contentType: "image/webp" });
  });
  // No media provider is invoked; Hero media is irrelevant to this regression.
  await page.route("**/*.mp4", (route) => route.abort());
  return { apiRequests, mediaRequests };
}

for (const width of [1440, 390]) {
  test(`renders actual summaries without workspace requests at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await mockApi(page);
    await page.goto("/");
    const section = page.getByRole("region", { name: "Recent Projects" });
    await section.scrollIntoViewIfNeeded();
    await expect(section.locator("[data-project-id]")).toHaveCount(4);
    await expect(section.getByRole("button", { name: "View all" })).toHaveCount(0);
    await expect(section.locator(".section-title p")).toHaveCount(0);
    await expect(section.locator(".home-recent-actions")).toHaveCount(0);
    await section.scrollIntoViewIfNeeded();
    await expect(section.getByText("No cover yet")).toHaveCount(2);
    for (const img of await section.locator("img").all()) {
      await img.scrollIntoViewIfNeeded();
      await expect.poll(() => img.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    }
    expect(requests.mediaRequests.sort()).toEqual(["/media/recent-poster-1.webp", "/media/recent-preview-0.webp"]);
    expect(requests.apiRequests.filter((url) => !url.endsWith("/health"))).toEqual(["/api/v2/projects?status=active&limit=4"]);
    await expect(section.locator("video")).toHaveCount(0);
    await expect(section.getByText("New fragrance product reel")).toHaveCount(0);
    expect(await section.locator("[data-project-id]").first().evaluate((element) => getComputedStyle(element).backgroundImage)).not.toContain("card1");
    for (const card of await section.locator("[data-project-id]").all()) {
      await expect.poll(async () => (await card.boundingBox())?.height).toBe(208);
      const box = await card.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
      expect(box!.height).toBe(208);
    }
    await section.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/home-recent-projects-${width}.png`, fullPage: true });
  });
}

for (const index of [0, 1, 2, 3]) {
  test(`card ${index} navigates with project identity rather than workflow identity`, async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await page.getByRole("region", { name: "Recent Projects" }).scrollIntoViewIfNeeded();
    const card = page.getByRole("button", { name: `Open ${fixtures[index].name}`, exact: true });
    await card.scrollIntoViewIfNeeded();
    await card.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/workflow/${fixtures[index].project_id}$`));
  });
}

test("retries a local error, then renders empty state without demo cards", async ({ page }) => {
  let failed = true;
  await mockApi(page, () => failed ? { status: 503 } : { items: [] });
  await page.goto("/");
  const section = page.getByRole("region", { name: "Recent Projects" });
  await section.scrollIntoViewIfNeeded();
  await expect(section.getByRole("alert")).toContainText("could not be refreshed");
  await expect(section.getByText("No recent projects")).toHaveCount(0);
  failed = false;
  await section.getByRole("button", { name: "Retry" }).click();
  await expect(section.getByText("No recent projects")).toBeVisible();
  await expect(section.locator("[data-project-id]")).toHaveCount(0);
  await expect(section.getByRole("button", { name: "Create project", exact: true })).toBeVisible();
});

test("broken cover falls back without preventing project navigation", async ({ page }) => {
  await mockApi(page);
  await page.route("**/media/recent-preview-0.webp*", (route) => route.fulfill({ status: 404 }));
  await page.goto("/");
  await page.getByRole("region", { name: "Recent Projects" }).scrollIntoViewIfNeeded();
  const card = page.getByRole("button", { name: "Open Real campaign 0" });
  await card.scrollIntoViewIfNeeded();
  await expect(card.getByText("Cover unavailable")).toBeVisible();
  await card.click();
  await expect(page).toHaveURL(/\/workflow\/project-recent-0$/);
});

test("does not load the Recent module or catalog while far outside the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 300 });
  const { apiRequests } = await mockApi(page);
  const modules: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/home/HomeRecentProjects")) modules.push(request.url()); });
  await page.goto("/");
  const section = page.getByRole("region", { name: "Recent Projects" });
  await expect(section.getByRole("status")).toHaveCount(1);
  await page.waitForTimeout(350);
  expect(modules).toEqual([]);
  expect(apiRequests.filter((url) => url.startsWith("/api/v2/projects"))).toEqual([]);
  await section.scrollIntoViewIfNeeded();
  await expect(section.locator("[data-project-id]")).toHaveCount(4);
  expect(apiRequests.filter((url) => url.startsWith("/api/v2/projects"))).toHaveLength(1);
});
