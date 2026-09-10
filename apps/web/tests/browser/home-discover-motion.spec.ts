import { expect, test, type Page } from "@playwright/test";

const fixture = "/tests/browser/home-discover-motion-mock.html";
const cardSelector = ".discover-orbit__card";

async function openGallery(page: Page, width = 1280) {
  await page.setViewportSize({ width, height: 720 });
  await page.goto(fixture);
  await expect(page.locator(cardSelector)).toHaveCount(16);
}

async function showGallery(page: Page) {
  await page.locator(".discover-orbit").evaluate((root) => {
    window.scrollTo(0, root.getBoundingClientRect().top + window.scrollY - 100);
  });
  await page.waitForTimeout(150); // Let IO/scroll settle before sampling motion.
}

async function sampleMotion(page: Page, duration = 400) {
  return page.evaluate(async (sampleMs) => {
    let writes = 0;
    let frames = 0;
    const setProperty = CSSStyleDeclaration.prototype.setProperty;
    const raf = window.requestAnimationFrame;
    CSSStyleDeclaration.prototype.setProperty = function (name, value, priority) {
      if (name.startsWith("--discover-track-")) writes += 1;
      return setProperty.call(this, name, value, priority);
    };
    // This fixture has only Discover scheduling RAF; count requests, not FPS.
    window.requestAnimationFrame = (callback) => {
      frames += 1;
      return raf.call(window, callback);
    };
    try {
      await new Promise((resolve) => window.setTimeout(resolve, sampleMs));
      return { writes, frames };
    } finally {
      CSSStyleDeclaration.prototype.setProperty = setProperty;
      window.requestAnimationFrame = raf;
    }
  }, duration);
}

test("offscreen gallery does no continuous work and resumes with the same cards", async ({ page }) => {
  await openGallery(page);
  await page.waitForTimeout(150);
  expect(await sampleMotion(page)).toEqual({ writes: 0, frames: 0 });
  const firstCard = await page.locator(cardSelector).first().elementHandle();
  await showGallery(page);
  const active = await sampleMotion(page);
  expect(active.writes).toBeGreaterThan(0);
  expect(active.frames).toBeGreaterThan(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
  expect(await sampleMotion(page)).toEqual({ writes: 0, frames: 0 });
  await showGallery(page);
  expect(await firstCard!.evaluate((card) => card === document.querySelector(".discover-orbit__card"))).toBe(true);
  expect((await sampleMotion(page)).writes).toBeGreaterThan(0);
});

for (const width of [1280, 390]) {
  test(`vertical wheel scrolls the page inside Discover at ${width}px`, async ({ page }) => {
    await openGallery(page, width);
    await showGallery(page);
    await page.mouse.move(width / 2, 350);
    const before = await page.evaluate(() => window.scrollY);
    await page.mouse.wheel(0, 280);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before + 200);
  });
}

test("desktop horizontal wheel still browses the orbit without vertical scroll", async ({ page }) => {
  await openGallery(page);
  await showGallery(page);
  const first = page.locator(cardSelector).first();
  const before = await first.evaluate((card) => parseFloat((card as HTMLElement).style.getPropertyValue("--discover-track-x")));
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await page.mouse.move(640, 350);
  await page.mouse.wheel(240, 0);
  await expect.poll(async () => {
    const current = await first.evaluate((card) => parseFloat((card as HTMLElement).style.getPropertyValue("--discover-track-x")));
    return Math.abs(current - before);
  }).toBeGreaterThan(50);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);
});

test("compact grid is stationary and every card can activate without centering", async ({ page }) => {
  await openGallery(page, 390);
  await showGallery(page);
  expect(await sampleMotion(page)).toEqual({ writes: 0, frames: 0 });
  await expect(page.locator(cardSelector).first()).toHaveCSS("transform", "none");
  await page.getByRole("button", { name: "upper Inspiration 1", exact: true }).click();
  await expect(page.getByLabel("Selection count")).toHaveText("1");
  await page.getByRole("button", { name: "lower Inspiration 8", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Selection count")).toHaveText("2");
  expect(await sampleMotion(page)).toEqual({ writes: 0, frames: 0 });
});

test("820/821 breakpoint stops and restarts motion without rebuilding cards", async ({ page }) => {
  await openGallery(page, 821);
  await showGallery(page);
  const firstCard = await page.locator(cardSelector).first().elementHandle();
  expect((await sampleMotion(page)).writes).toBeGreaterThan(0);
  await page.setViewportSize({ width: 820, height: 720 });
  await showGallery(page);
  expect(await sampleMotion(page)).toEqual({ writes: 0, frames: 0 });
  await expect(page.locator(cardSelector).first()).toHaveCSS("transform", "none");
  await page.setViewportSize({ width: 821, height: 720 });
  await showGallery(page);
  expect((await sampleMotion(page)).writes).toBeGreaterThan(0);
  expect(await firstCard!.evaluate((card) => card === document.querySelector(".discover-orbit__card"))).toBe(true);
});

test("desktop drag and arrow-key browsing retain their existing motion", async ({ page }) => {
  await openGallery(page);
  await showGallery(page);
  const first = page.locator(cardSelector).first();
  const readX = () => first.evaluate((card) => parseFloat((card as HTMLElement).style.getPropertyValue("--discover-track-x")));
  const beforeDrag = await readX();
  // Drag the orbit's blank top gutter. Images trigger native drag/pointercancel
  // in the baseline too; changing that separate interaction is out of scope.
  await page.mouse.move(640, 140);
  await page.mouse.down();
  await page.mouse.move(370, 140, { steps: 10 });
  await page.mouse.up();
  await expect.poll(async () => Math.abs(await readX() - beforeDrag)).toBeGreaterThan(50);
  const active = page.locator('[data-discover-track="upper"] [aria-current="true"]');
  await active.focus();
  await page.waitForTimeout(900); // Preserve existing damped center-then-browse behavior.
  const beforeArrow = await readX();
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => Math.abs(await readX() - beforeArrow)).toBeGreaterThan(50);
});
