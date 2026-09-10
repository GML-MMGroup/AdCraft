import { expect, test, type Page } from "@playwright/test";

const ROOT = '[data-agent-role="script-writer"]';

async function startWriting(page: Page): Promise<void> {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "Script Writer", exact: true }).click();
  await page.getByRole("button", { name: "Idle", exact: true }).click();
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await page.waitForFunction((selector) => {
    const animations = document.querySelector(selector)!.getAnimations({ subtree: true });
    return animations.length === 13 && animations.every((a) => a.effect!.getTiming().duration === 3200);
  }, ROOT);
}

async function seek(page: Page, time: number): Promise<void> {
  await page.locator(ROOT).evaluate((root, currentTime) => {
    for (const animation of root.getAnimations({ subtree: true })) {
      animation.pause();
      animation.currentTime = currentTime;
    }
  }, time);
}

test("unwritten rows have no leading dots, and the revealing edge follows the pen tip", async ({ page }) => {
  await startWriting(page);
  for (const [time, hiddenRows, writingRow] of [[600, [2, 3, 4], 1], [1400, [3, 4], 2], [2400, [4], 3]] as const) {
    await seek(page, time);
    for (const row of hiddenRows) {
      await expect(page.locator(`${ROOT} [data-part="writing-row-${row}"]`)).toHaveCSS("opacity", "0");
    }
    const tipError = await page.locator(ROOT).evaluate((root, row) => {
      const pen = root.querySelector<SVGGraphicsElement>('[data-part="writing-pen"]')!;
      const position = root.querySelector<SVGGraphicsElement>(`[data-part="row-position-${row - 1}"]`)!;
      const mask = root.querySelector(`[data-part="writing-row-${row}"]`)!;
      const tip = new DOMPoint(170, 230).matrixTransform(pen.getCTM()!);
      const edge = new DOMPoint(170, 0)
        .matrixTransform(new DOMMatrix(getComputedStyle(mask).transform))
        .matrixTransform(position.getCTM()!);
      return Math.hypot(tip.x - edge.x, tip.y - edge.y);
    }, writingRow);
    expect(tipError).toBeLessThan(0.05);
  }
  await seek(page, 920);
  await expect(page.locator(`${ROOT} [data-part="writing-pen"]`)).toHaveCSS("opacity", "1");
});

test("intro hands off seamlessly and three continuation cycles keep fixed row and animation counts", async ({ page }) => {
  await startWriting(page);
  const root = page.locator(ROOT);
  const nodeCount = await root.locator("*").count();
  await seek(page, 3200);
  const before = await root.locator("[data-part]").evaluateAll((parts) => parts.map((part) => ({
    part: part.getAttribute("data-part"), transform: getComputedStyle(part).transform, opacity: getComputedStyle(part).opacity,
  })));
  await root.evaluate((element) => {
    for (const animation of element.getAnimations({ subtree: true })) animation.finish();
  });
  await page.waitForFunction((selector) => {
    const animations = document.querySelector(selector)!.getAnimations({ subtree: true });
    return animations.length === 13 && animations.every((a) => a.effect!.getTiming().iterations === Infinity);
  }, ROOT);
  await seek(page, 0);
  const after = await root.locator("[data-part]").evaluateAll((parts) => parts.map((part) => ({
    part: part.getAttribute("data-part"), transform: getComputedStyle(part).transform, opacity: getComputedStyle(part).opacity,
  })));
  expect(after).toEqual(before);

  const seamPoses = [];
  for (const time of [6399, 6401]) {
    await seek(page, time);
    seamPoses.push(await root.evaluate((element) => {
      const rows = [...element.querySelectorAll<SVGGraphicsElement>("[data-writing-row]")]
        .filter((row) => {
          const y = new DOMMatrix(getComputedStyle(row).transform).f;
          return y > 210 && y < 330;
        })
        .map((row) => {
          const index = Number(row.dataset.writingRow);
          const mask = element.querySelector(`[data-part="writing-row-${index}"]`)!;
          return { index, transform: getComputedStyle(row).transform, reveal: getComputedStyle(mask).transform, opacity: getComputedStyle(mask).opacity };
        });
      const pen = element.querySelector('[data-part="writing-pen"]')!;
      return { rows, penX: new DOMMatrix(getComputedStyle(pen).transform).e };
    }));
  }
  expect(seamPoses[1].rows).toEqual(seamPoses[0].rows);
  expect(seamPoses[0].rows).toHaveLength(3);
  expect(Math.abs(seamPoses[1].penX - seamPoses[0].penX)).toBeLessThan(0.05);

  for (const time of [6399, 6401, 12801, 19201]) {
    await seek(page, time);
    await expect(root.locator("[data-writing-row]")).toHaveCount(4);
    expect(await root.locator("*").count()).toBe(nodeCount);
    expect(await root.evaluate((element) => element.getAnimations({ subtree: true }).length)).toBe(13);
    await expect(root.locator('[data-part="writing-pen"]')).toHaveCSS("opacity", "1");
  }
  await root.evaluate((element) => {
    for (const animation of element.getAnimations({ subtree: true })) animation.play();
  });
  await expect.poll(() => root.evaluate((element) => element.getAnimations({ subtree: true })
    .every((a) => a.playState === "running" && Number(a.currentTime) > 19201))).toBe(true);
  await page.getByRole("button", { name: "Idle", exact: true }).click();
  await expect.poll(() => root.evaluate((element) => element.getAnimations({ subtree: true }).length)).toBe(0);
});

test("reduced motion cancels writing and leaves complete static rows", async ({ page }) => {
  await startWriting(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => page.locator(ROOT).evaluate((element) => element.getAnimations({ subtree: true }).length)).toBe(0);
  for (const row of [1, 2, 3]) {
    await expect(page.locator(`${ROOT} [data-part="writing-row-${row}"]`)).toHaveCSS("opacity", "1");
  }
});
