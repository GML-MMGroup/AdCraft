import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", (route) => route.abort());
  await page.route("**/api/v2/**", (route) => route.abort());
});

async function gap(page: Page, label = "Choose model") {
  const trigger = (await page.locator(`summary[aria-label="${label}"]`).boundingBox())!;
  const menu = (await page.getByRole("listbox").boundingBox())!;
  return trigger.y - menu.y - menu.height;
}

test("Text model menu is anchored on its first visible frame without an opening delay", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?textPanel=draft");
  await page.locator(".agent-node-workbench").evaluate((el: HTMLElement) => {
    Object.assign(el.style, { position: "fixed", left: "240px", top: "650px" });
  });
  const measurements = await page.evaluate(async () => {
    const trigger = document.querySelector<HTMLElement>('summary[aria-label="Choose model"]')!;
    const start = performance.now();
    const samples: { elapsed: number; gap: number }[] = [];
    trigger.click();
    for (let i = 0; i < 8; i++) {
      await new Promise(requestAnimationFrame);
      const menu = document.querySelector<HTMLElement>('[role="listbox"]');
      if (menu && getComputedStyle(menu).visibility === "visible") {
        samples.push({ elapsed: performance.now() - start, gap: trigger.getBoundingClientRect().top - menu.getBoundingClientRect().bottom });
      }
    }
    return samples;
  });
  expect(measurements.length).toBeGreaterThan(0);
  expect(measurements.every((sample) => Math.abs(sample.gap - 5) < 1)).toBe(true);
  expect(measurements[0].elapsed).toBeLessThan(100);
  await page.screenshot({ path: "/tmp/workbench-menu-anchor-text.png" });
  console.log("Text menu first visible frame (ms):", measurements[0].elapsed);
});

for (const query of ["textPanel=draft", "provider=1&modelMenu=1", "videoToolbar=1"]) {
  test(`shared model menu remains anchored after resize and reopen: ${query}`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?${query}`);
    await page.locator(".agent-node-workbench").evaluate((el: HTMLElement) => {
      Object.assign(el.style, { position: "fixed", left: "24px", bottom: "24px" });
    });
    await page.getByLabel("Choose model", { exact: true }).click();
    await expect.poll(() => gap(page)).toBeCloseTo(5, 1);
    const menu = page.getByRole("listbox");
    await menu.evaluate((el) => {
      const extra = document.createElement("div");
      extra.dataset.testExtra = "1";
      extra.style.height = "48px";
      el.appendChild(extra);
    });
    await expect.poll(() => gap(page)).toBeCloseTo(5, 1);
    await menu.locator('[data-test-extra="1"]').evaluate((el) => el.remove());
    await expect.poll(() => gap(page)).toBeCloseTo(5, 1);
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await page.getByLabel("Choose model", { exact: true }).click();
    await expect.poll(() => gap(page)).toBeCloseTo(5, 1);
    await page.setViewportSize({ width: 390, height: 640 });
    await expect.poll(() => gap(page)).toBeCloseTo(5, 1);
    const bounds = (await menu.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(12);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(378);
    expect(bounds.y).toBeGreaterThanOrEqual(12);
    await page.screenshot({ path: `/tmp/workbench-menu-anchor-${query.replaceAll(/[^a-z]/gi, "-")}-mobile.png` });
  });
}

test("video parameter menu uses the same measured anchor and keyboard selection", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?videoToolbar=1");
  await page.locator(".agent-node-workbench").evaluate((el: HTMLElement) => {
    Object.assign(el.style, { position: "fixed", left: "240px", bottom: "24px" });
  });
  const trigger = page.locator('summary[aria-label="Resolution"]');
  await trigger.click();
  await expect.poll(() => gap(page, "Resolution")).toBeCloseTo(5, 1);
  await page.keyboard.press("End");
  await expect(page.getByRole("option", { name: "1080p" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("moves below when the previous side cannot display an option", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?textPanel=draft");
  const panel = page.locator(".agent-node-workbench");
  await panel.evaluate((el: HTMLElement) => Object.assign(el.style, { position: "fixed", left: "240px", top: "650px" }));
  await page.getByLabel("Choose model", { exact: true }).click();
  await expect.poll(() => gap(page)).toBeCloseTo(5, 1);
  await panel.evaluate((el: HTMLElement) => {
    const trigger = el.querySelector("summary")!.getBoundingClientRect();
    el.style.top = `${el.getBoundingClientRect().top + 18 - trigger.top}px`;
    window.dispatchEvent(new Event("scroll"));
  });
  await expect.poll(async () => (await page.getByRole("listbox").boundingBox())!.y).toBeCloseTo(55, 1);
  expect((await page.getByRole("listbox").boundingBox())!.height).toBeGreaterThan(48);
  await expect(page.getByRole("option").first()).toBeVisible();
});
