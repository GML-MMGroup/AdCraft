import { expect, test, type Page } from "@playwright/test";

const fixture = "/tests/browser/agent-role-runtime-panel-mock.html";
const scene = ".agent-chat__stage-thread > header .is-role-scene-design";

async function sampleIdentity(page: Page) {
  await page.addInitScript(() => {
    const samples = { bareFrames: 0, firstText: 0, firstIcon: 0 };
    Object.assign(window, { roleIdentitySamples: samples });
    const visible = (element: Element | null): boolean => {
      if (!element) return false;
      for (let cursor: Element | null = element; cursor; cursor = cursor.parentElement) {
        const style = getComputedStyle(cursor);
        if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity) === 0) return false;
      }
      return element.getBoundingClientRect().width > 0;
    };
    const frame = (time: number) => {
      const row = document.querySelector(".agent-chat__stage-thread > header .is-role-scene-design");
      const text = row?.querySelector("strong") ?? null;
      const image = row?.querySelector("img");
      const svg = row?.querySelector("svg") ?? null;
      const generic = row?.querySelector('[data-role-generic-fallback="true"]') ?? null;
      const icon = (visible(svg) && !!svg?.querySelector("path, circle, rect, g"))
        || (visible(image ?? null) && !!image?.complete && image.naturalWidth > 0)
        || visible(generic);
      if (visible(text)) {
        if (!samples.firstText) samples.firstText = time;
        if (!icon) samples.bareFrames += 1;
      }
      if (icon && !samples.firstIcon) samples.firstIcon = time;
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  });
}

test("slow bitmap resources never reveal a naked role name", async ({ page }) => {
  await sampleIdentity(page);
  await page.route(/agent-role-icons|\/roles\/.*Animation\.tsx/, async route => {
    await new Promise(resolve => setTimeout(resolve, 800));
    await route.continue();
  });
  await page.goto(fixture);
  await expect(page.locator(scene).getByText("Scene Designer", { exact: true })).toBeVisible();
  await page.waitForTimeout(1800);
  const sample = await page.evaluate(() => (window as unknown as {
    roleIdentitySamples: { bareFrames: number; firstText: number; firstIcon: number };
  }).roleIdentitySamples);
  expect(sample.firstIcon).toBeGreaterThan(0);
  expect(sample.firstText).toBeGreaterThan(0);
  expect(sample.bareFrames).toBe(0);
});

test("working Role content and its SVG Artwork enter the Timeline together", async ({ page }) => {
  await page.route("**/roles/SceneDesignerAnimation.tsx*", async route => {
    await new Promise(resolve => setTimeout(resolve, 800));
    await route.continue();
  });
  await page.goto(fixture, { waitUntil: "commit" });
  const observations: Array<{ text: number; svg: number }> = [];
  for (let index = 0; index < 20; index += 1) {
    observations.push({
      text: await page.locator(scene).getByText("Scene Designer", { exact: true }).count(),
      svg: await page.locator(scene).locator("svg").count(),
    });
    await page.waitForTimeout(50);
  }
  expect(observations.some(({ text, svg }) => text === 1 && svg === 1)).toBe(true);
  expect(observations.some(({ text, svg }) => text > 0 && svg === 0)).toBe(false);
});

test("completed role uses a decoded bitmap without fetching its animation module", async ({ page }) => {
  await page.goto(fixture);
  const world = page.locator(".agent-chat__stage-thread > header .is-role-world-setting");
  await expect(world.getByText("World Setting", { exact: true })).toBeVisible();
  await expect.poll(() => world.locator("img").evaluate(image =>
    image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0)).toBe(true);
  await expect(world.locator("svg")).toHaveCount(0);
});

test("working roles use bundled Artwork without a retry or fallback visual", async ({ page }) => {
  await page.goto(fixture);
  const identity = page.locator(scene);
  await expect(identity.locator("svg")).toHaveCount(1);
  await expect(identity.locator("img")).toHaveCount(0);
  await expect(identity.getByRole("button", { name: /Retry .* icon/ })).toHaveCount(0);
  await expect(page.getByText("Conversation could not be refreshed")).toHaveCount(0);
});

test("missing remote bitmaps fall back without leaving a blank identity", async ({ page }) => {
  await sampleIdentity(page);
  await page.route("**/bitmaps-v1/*.png*", route => route.abort());
  await page.goto(fixture);
  const identity = page.locator(".agent-chat__stage-thread > header .is-role-world-setting");
  await expect(identity.getByText("World Setting", { exact: true })).toBeVisible();
  await expect.poll(() => identity.locator("img").evaluate(image =>
    image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0)).toBe(true);
  expect(await page.evaluate(() => (window as unknown as { roleIdentitySamples: { bareFrames: number } }).roleIdentitySamples.bareFrames)).toBe(0);
});

test("remount uses already decoded bitmaps without downloading them again", async ({ page }) => {
  const bitmaps: string[] = [];
  page.on("request", request => { if (request.url().includes("/bitmaps-v1/")) bitmaps.push(request.url()); });
  await page.goto(fixture);
  await expect(page.locator(scene).locator("svg")).toHaveCount(1);
  const count = bitmaps.length;
  await page.getByRole("button", { name: "Unmount panel", exact: true }).click();
  await page.getByRole("button", { name: "Mount panel", exact: true }).click();
  await expect(page.locator(scene).getByText("Scene Designer", { exact: true })).toBeVisible();
  await expect(page.locator(scene)).toHaveAttribute("data-role-identity-state", "ready");
  expect(bitmaps).toHaveLength(count);
});

test("stalled image decoding releases the whole identity with a paintable fallback", async ({ page }) => {
  await sampleIdentity(page);
  await page.addInitScript(() => {
    const decode = HTMLImageElement.prototype.decode;
    HTMLImageElement.prototype.decode = function () {
      if (this.src.includes("/bitmaps-v1/") || this.src.startsWith("data:image/png;base64,")) {
        return new Promise<void>(() => undefined);
      }
      return decode.call(this);
    };
  });
  await page.goto(fixture);
  const identity = page.locator(".agent-chat__stage-thread > header .is-role-world-setting");
  await expect(identity).toHaveAttribute("data-role-identity-state", "fallback");
  await expect(identity.locator('[data-role-generic-fallback="true"]')).toBeVisible();
  await expect(identity.getByText("World Setting", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { roleIdentitySamples: { bareFrames: number } }).roleIdentitySamples.bareFrames)).toBe(0);
});
