import { expect, test, type Page } from "@playwright/test";

const ROOT = '[data-agent-role="character-designer"]';
const ORIGINAL = "/imgs/agent-role-icons/character-designer-20260906-line-art.svg";

async function compareBitmapToOriginal(page: Page, original: string, dpr: number) {
  return page.getByTestId("agent-role-static-icon").evaluate(async (element, { original, dpr }) => {
    const load = async (source: string) => { const image = new Image(); image.src = source; await image.decode(); return image; };
    const [bitmap, reference] = await Promise.all([load((element as HTMLImageElement).src), load(original)]);
    const size = 32 * dpr;
    const pixels = (image: HTMLImageElement) => { const canvas = document.createElement("canvas"); canvas.width = canvas.height = size;
      const context = canvas.getContext("2d")!; context.drawImage(image, 0, 0, size, size); return context.getImageData(0, 0, size, size).data; };
    const left = pixels(bitmap), right = pixels(reference); let difference = 0, changed = 0, alphaUnion = 0, alphaMismatch = 0;
    for (let index = 0; index < left.length; index += 4) { let pixelDifference = 0;
      for (let channel = 0; channel < 4; channel += 1) pixelDifference += Math.abs(left[index + channel] - right[index + channel]);
      difference += pixelDifference; if (pixelDifference > 32) changed += 1;
      if (left[index + 3] > 16 || right[index + 3] > 16) { alphaUnion += 1;
        if ((left[index + 3] > 16) !== (right[index + 3] > 16)) alphaMismatch += 1; }
    }
    return { meanChannelDifference: difference / left.length, changedPixelRatio: changed / (size * size),
      alphaMismatchRatio: alphaMismatch / alphaUnion };
  }, { original, dpr });
}

test("minimal jacket has empty fabric regions and an attached shoulder seam", async ({ page }) => {
  await start(page);
  const geometry = await page.locator(ROOT).evaluate((root) => {
    const getPath = (selector: string) => root.querySelector<SVGPathElement>(selector)!;
    const seam = getPath('[data-completed-stroke="collar-detail"]');
    const first = seam.getPointAtLength(0), last = seam.getPointAtLength(seam.getTotalLength());
    const outline = getPath('[data-garment="outline"]');
    const collar = getPath('[data-completed-stroke="left-lapel"]');
    const distanceToPath = (point: DOMPoint, path: SVGPathElement) => {
      let distance = Infinity;
      for (let length = 0; length <= path.getTotalLength(); length += 0.1) {
        const sample = path.getPointAtLength(length);
        distance = Math.min(distance, Math.hypot(point.x - sample.x, point.y - sample.y));
      }
      return distance;
    };
    const samples = Array.from({ length: 101 }, (_, i) => seam.getPointAtLength(seam.getTotalLength() * i / 100).x);
    return {
      fabricPlanes: root.querySelectorAll('[data-garment="body"], [data-garment="front"], [data-garment="inner"], [data-collar-fabric]').length,
      outlineFill: getComputedStyle(outline).fill,
      attachment: [distanceToPath(first, outline), distanceToPath(last, collar)],
      monotonic: samples.every((x, i) => i === 0 || x >= samples[i - 1]),
      garmentAnimations: root.getAnimations({ subtree: true }).filter((animation) =>
        (animation.effect as KeyframeEffect).target?.hasAttribute("data-garment")).length,
    };
  });
  expect(geometry.fabricPlanes).toBe(0);
  expect(geometry.outlineFill).toBe("none");
  geometry.attachment.forEach((distance) => expect(distance).toBeLessThan(0.1));
  expect(geometry.monotonic).toBe(true);
  expect(geometry.garmentAnimations).toBe(0);
});

test("short collar keeps continuous native lapel edges without a low chest junction", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "Character Designer", exact: true }).click();
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await expect(page.locator(ROOT)).toBeVisible();
  const geometry = await page.locator(ROOT).evaluate((root) => {
    const left = root.querySelector<SVGPathElement>('[data-completed-stroke="left-lapel"]')!;
    const right = root.querySelector<SVGPathElement>('[data-completed-stroke="right-lapel"]')!;
    const a = left.getPointAtLength(left.getTotalLength()), b = right.getPointAtLength(0);
    return {
      jointDistance: Math.hypot(a.x - b.x, a.y - b.y),
      edges: [left, right].map((path) => {
        const box = path.getBBox();
        const active = root.querySelector<SVGPathElement>(`[data-active-stroke="${path.dataset.completedStroke}"]`)!;
        return { bottom: box.y + box.height, activePath: active.getAttribute("d"), completedPath: path.getAttribute("d") };
      }),
    };
  });
  expect(geometry.jointDistance).toBeLessThan(0.01);
  for (const edge of geometry.edges) {
    expect(edge.bottom).toBeLessThanOrEqual(390);
    expect(edge.activePath).toBe(edge.completedPath);
  }
});

async function start(page: Page) {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "Character Designer", exact: true }).click();
  await page.getByRole("button", { name: "Idle", exact: true }).click();
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await page.waitForFunction((selector) => {
    const animations = document.querySelector(selector)!.getAnimations({ subtree: true });
    return animations.length === 16 && animations.every((a) => a.effect!.getTiming().duration === 4800);
  }, ROOT);
}

async function seek(page: Page, time: number) {
  await page.locator(ROOT).evaluate((root, time) => {
    for (const animation of root.getAnimations({ subtree: true })) { animation.pause(); animation.currentTime = time; }
  }, time);
}

test("drawing retains intrinsic colors in construction, refinement and Waiting", async ({ page }) => {
  await start(page);
  const assertColors = async () => {
    const colors = await page.locator(ROOT).evaluate((root) => [...root.querySelectorAll<SVGPathElement>("[data-active-stroke]")].map((path) => {
      const completed = root.querySelector(`[data-completed-stroke="${path.dataset.activeStroke}"]`)!;
      const activeStyle = getComputedStyle(path), completedStyle = getComputedStyle(completed);
      return { id: path.dataset.activeStroke, active: [activeStyle.stroke, activeStyle.strokeWidth], completed: [completedStyle.stroke, completedStyle.strokeWidth] };
    }));
    expect(colors).toHaveLength(9);
    for (const color of colors) {
      expect(color.active).toEqual(color.completed);
      expect(color.active).toEqual(color.id === "right-lapel" ? ["rgb(255, 179, 35)", "5px"]
        : color.id!.endsWith("-detail") ? ["rgb(120, 153, 226)", "6px"] : ["rgb(250, 251, 255)", "8px"]);
    }
    await expect(page.locator(`${ROOT} [data-pencil-grip]`)).toHaveCSS("fill", "rgb(255, 179, 35)");
  };
  for (const time of [900, 2100, 3600]) { await seek(page, time); await assertColors(); }
  await page.locator(ROOT).evaluate((el) => el.getAnimations({ subtree: true }).forEach((a) => a.finish()));
  await page.waitForFunction((selector) => {
    const animations = document.querySelector(selector)!.getAnimations({ subtree: true });
    return animations.length === 16 && animations.every((a) => a.effect!.getTiming().iterations === Infinity);
  }, ROOT);
  for (const time of [900, 2100, 3600]) { await seek(page, time); await assertColors(); }
  await page.getByRole("button", { name: "Waiting", exact: true }).click();
  await assertColors();
  await expect(page.locator(`${ROOT} [data-part="reveal-right-lapel"]`)).toHaveCSS("opacity", "1");
  await expect(page.locator(`${ROOT} [data-completed-stroke="right-lapel"]`)).toHaveCSS("opacity", "1");
});

test("drawing follows native curves without future dots or an out-of-bounds pencil", async ({ page }) => {
  await start(page);
  await seek(page, 900);
  for (const id of ["forehead", "chin", "jaw", "left-lapel", "right-lapel"]) {
    await expect(page.locator(`${ROOT} [data-part="reveal-${id}"]`)).toHaveCSS("opacity", "0");
  }
  for (const phase of ["construction", "refinement"]) {
    if (phase === "refinement") {
      await seek(page, 4800);
      await page.locator(ROOT).evaluate((el) => el.getAnimations({ subtree: true }).forEach((a) => a.finish()));
      await page.waitForFunction((selector) => {
        const animations = document.querySelector(selector)!.getAnimations({ subtree: true });
        return animations.length === 16 && animations.every((a) => a.effect!.getTiming().iterations === Infinity);
      }, ROOT);
    }
    for (const time of [600, 950, 1600, 1900, 2300, 2500, 3000, 3650, 3900]) {
      await seek(page, time);
      const errors = await page.locator(ROOT).evaluate((root) => {
        const pen = new DOMMatrix(getComputedStyle(root.querySelector('[data-part="design-pencil"]')!).transform);
        return [...root.querySelectorAll<SVGPathElement>("[data-active-stroke]")].flatMap((path) => {
          const mask = root.querySelector(`[data-part="reveal-${path.dataset.activeStroke}"]`)!;
          const style = getComputedStyle(mask);
          const matrix = new DOMMatrix(style.transform);
          const axis = Number(mask.getAttribute("x")) < 0 ? "x" : "y";
          const coordinate = axis === "x" ? matrix.e : matrix.f;
          if (style.opacity === "0" || coordinate >= 511) return [];
          let low = 0, high = path.getTotalLength();
          for (let i = 0; i < 32; i++) {
            const mid = (low + high) / 2;
            if (path.getPointAtLength(mid)[axis] < coordinate) low = mid; else high = mid;
          }
          const edge = path.getPointAtLength((low + high) / 2);
          return [Math.hypot(pen.e - edge.x, pen.f - edge.y)];
        });
      });
      expect(errors).toHaveLength(1);
      expect(errors[0]).toBeLessThan(0.35);
    }
    const bounds = await page.locator(ROOT).evaluate((root) => {
      const animations = root.getAnimations({ subtree: true });
      const pencil = root.querySelector<SVGGraphicsElement>('[data-part="design-pencil"]')!;
      const box = pencil.getBBox();
      const corners = [[box.x, box.y], [box.x + box.width, box.y], [box.x, box.y + box.height], [box.x + box.width, box.y + box.height]];
      let minX = 512, minY = 512, maxX = 0, maxY = 0;
      for (let time = 0; time < 4800; time += 25) {
        animations.forEach((a) => { a.currentTime = time; });
        const matrix = new DOMMatrix(getComputedStyle(pencil).transform);
        for (const [x, y] of corners) {
          const p = new DOMPoint(x, y).matrixTransform(matrix);
          minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
          maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y);
        }
        if (getComputedStyle(pencil).opacity !== "1") throw new Error("Pencil disappeared");
      }
      return { minX, minY, maxX, maxY };
    });
    expect(bounds.minX).toBeGreaterThanOrEqual(40);
    expect(bounds.minY).toBeGreaterThanOrEqual(40);
    expect(bounds.maxX).toBeLessThanOrEqual(472);
    expect(bounds.maxY).toBeLessThanOrEqual(472);
  }
});

test("construction and refinement have matching seams and bounded long-running playback", async ({ page }) => {
  await start(page);
  const root = page.locator(ROOT);
  const nodes = await root.locator("*").count();
  const poses = () => root.locator("[data-part]").evaluateAll((elements) => elements.map((el) => ({
    name: el.getAttribute("data-part"), transform: getComputedStyle(el).transform, opacity: getComputedStyle(el).opacity,
  })));
  await seek(page, 4800);
  const end = await poses();
  await root.evaluate((el) => el.getAnimations({ subtree: true }).forEach((a) => a.finish()));
  await page.waitForFunction((selector) => document.querySelector(selector)!.getAnimations({ subtree: true })
    .every((a) => a.effect!.getTiming().iterations === Infinity), ROOT);
  await seek(page, 0);
  expect(await poses()).toEqual(end);
  await seek(page, 4799.99);
  const loopEnd = await poses();
  await seek(page, 4800.01);
  const loopStart = await poses();
  expect(loopStart.filter((pose) => pose.name !== "design-pencil")).toEqual(loopEnd.filter((pose) => pose.name !== "design-pencil"));
  const pencilComponents = (transform: string) => transform.match(/-?[\d.]+/g)!.map(Number);
  const beforePencil = pencilComponents(loopEnd.find((pose) => pose.name === "design-pencil")!.transform);
  const afterPencil = pencilComponents(loopStart.find((pose) => pose.name === "design-pencil")!.transform);
  afterPencil.forEach((value, i) => expect(Math.abs(value - beforePencil[i])).toBeLessThan(0.01));
  await seek(page, 14400);
  expect(await root.locator("*").count()).toBe(nodes);
  expect(await root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(16);
  await root.evaluate((el) => el.getAnimations({ subtree: true }).forEach((a) => a.play()));
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).every((a) => a.playState === "running" && Number(a.currentTime) > 14400))).toBe(true);
  await page.getByRole("button", { name: "Waiting", exact: true }).click();
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
});

for (const dpr of [1, 2]) {
  test(`terminal bitmap matches the original image at 32px DPR ${dpr}`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ deviceScaleFactor: dpr, baseURL });
    const page = await context.newPage();
    const moduleRequests: string[] = [];
    page.on("request", request => { if (request.url().includes("/roles/CharacterDesignerAnimation.tsx")) moduleRequests.push(request.url()); });
    await page.goto("/tests/browser/agent-role-character-designer-mock.html", { waitUntil: "domcontentloaded" });
    const poster = page.getByTestId("agent-role-static-icon");
    await expect(poster).toHaveAttribute("src", /\/bitmaps-v1\/character_design-96\.png/);
    await expect.poll(() => poster.evaluate((img) => (img as HTMLImageElement).complete && (img as HTMLImageElement).naturalWidth > 0)).toBe(true);
    const fidelity = await compareBitmapToOriginal(page, ORIGINAL, dpr);
    expect(fidelity.meanChannelDifference).toBeLessThanOrEqual(9);
    expect(fidelity.changedPixelRatio).toBeLessThanOrEqual(0.13);
    expect(fidelity.alphaMismatchRatio).toBeLessThanOrEqual(0.1);
    expect(moduleRequests).toEqual([]);
    await context.close();
  });
}

test("terminal state uses the readable bitmap without loading artwork", async ({ page }) => {
  const moduleRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("/roles/CharacterDesignerAnimation.tsx")) moduleRequests.push(request.url()); });
  await page.route("**/roles/CharacterDesignerAnimation.tsx*", (route) => route.abort());
  await page.goto("/tests/browser/agent-role-character-designer-mock.html");
  await expect(page.locator(ROOT)).toHaveCount(0);
  const poster = page.getByTestId("agent-role-static-icon");
  await expect(poster).toBeVisible();
  await expect(poster).toHaveAttribute("src", /\/bitmaps-v1\/character_design-96\.png/);
  await expect.poll(() => poster.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  expect(moduleRequests).toEqual([]);
});
