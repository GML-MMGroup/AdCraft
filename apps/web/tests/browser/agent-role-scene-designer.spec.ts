import { expect, test, type Page } from "@playwright/test";

const ROOT = '[data-agent-role="scene-designer"]';
const POSTER = "/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg";

async function startArtwork(page: Page) {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "Scene Designer", exact: true }).click();
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await expect(page.locator(ROOT)).toBeVisible();
}

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

test("atlas scene preserves the original open walls, right arch and offset sun", async ({ page }) => {
  await startArtwork(page);
  const root = page.locator(ROOT);
  await expect(root).toBeVisible();
  for (const name of ["left-wall", "right-wall", "back-wall", "arch", "floor-grid", "sun"]) {
    await expect(root.locator(`[data-scene-element="${name}"]`)).toHaveCount(1);
  }
  await expect(root.locator('[data-scene-line="sun-ray"]')).toHaveCount(8);
  await expect(root.locator('[data-scene-reference="atlas-row-2-col-1"]')).toHaveCount(1);
  await expect(root.locator("image, foreignObject, pattern")).toHaveCount(0);
  await expect(root.locator('[data-scene-element="tree"], [data-scene-step], [data-scene-detail="courtyard-wall"]')).toHaveCount(0);
  const geometry = await root.evaluate((element) => {
    const bounds = (name: string) => {
      const shape = element.querySelector<SVGGraphicsElement>(`[data-scene-element="${name}"]`)!;
      const { x, y, width, height } = shape.getBBox();
      return { x, y, width, height };
    };
    return {
      left: bounds("left-wall"), right: bounds("right-wall"), back: bounds("back-wall"),
      arch: bounds("arch"), floor: bounds("floor-grid"), sun: bounds("sun"),
      sunColors: [...element.querySelectorAll<SVGGraphicsElement>('[data-scene-element="sun"] circle, [data-scene-line="sun-ray"]')]
        .map((shape) => getComputedStyle(shape).stroke),
      archColors: [...element.querySelectorAll<SVGGraphicsElement>('[data-scene-element="arch"] path')]
        .map((shape) => getComputedStyle(shape).stroke),
    };
  });
  expect(geometry.left.x + geometry.left.width).toBeLessThan(geometry.right.x);
  expect(geometry.arch.x).toBeGreaterThan(geometry.right.x);
  expect(geometry.arch.x + geometry.arch.width).toBeLessThan(geometry.right.x + geometry.right.width);
  expect(geometry.arch.height).toBeGreaterThan(geometry.arch.width);
  expect(geometry.sun.y + geometry.sun.height).toBeLessThan(geometry.back.y);
  expect(geometry.sun.x + geometry.sun.width / 2)
    .toBeLessThan((geometry.left.x + geometry.right.x + geometry.right.width) / 2);
  expect(geometry.floor.width).toBeGreaterThan(geometry.back.width * 2);
  expect(geometry.sunColors).toHaveLength(9);
  expect(geometry.sunColors.every((color) => color === "rgb(255, 202, 98)")).toBe(true);
  expect(geometry.archColors).toEqual(expect.arrayContaining(["rgb(248, 250, 255)", "rgb(136, 171, 255)"]));
  expect(geometry.archColors).not.toContain("rgb(255, 202, 98)");
});

test("atlas floor grid widens and its cross-line spacing opens toward the viewer", async ({ page }) => {
  await startArtwork(page);
  const root = page.locator(ROOT);
  await expect(root).toBeVisible();
  await expect(root.locator('[data-scene-element="floor-grid"]')).toHaveCount(1);
  const grid = await root.evaluate((element) => {
    const crosses = [...element.querySelectorAll<SVGGraphicsElement>('[data-scene-line="grid-cross"]')]
      .map((shape) => {
        const { y, width } = shape.getBBox();
        return { y, width };
      }).sort((a, b) => a.y - b.y);
    const depth = [...element.querySelectorAll<SVGGeometryElement>('[data-scene-line="grid-depth"]')]
      .map((shape) => {
        const start = shape.getPointAtLength(0);
        const end = shape.getPointAtLength(shape.getTotalLength());
        return start.y < end.y ? { rearX: start.x, frontX: end.x } : { rearX: end.x, frontX: start.x };
      });
    return { crosses, depth };
  });
  expect(grid.crosses.length).toBeGreaterThanOrEqual(4);
  expect(grid.depth.length).toBeGreaterThanOrEqual(5);
  for (let i = 1; i < grid.crosses.length; i += 1) {
    expect(grid.crosses[i].width).toBeGreaterThan(grid.crosses[i - 1].width);
    expect(grid.crosses[i].y).toBeGreaterThan(grid.crosses[i - 1].y);
  }
  const last = grid.crosses.length - 1;
  expect(grid.crosses[last].y - grid.crosses[last - 1].y)
    .toBeGreaterThan(grid.crosses[1].y - grid.crosses[0].y);
  const spread = (values: number[]) => Math.max(...values) - Math.min(...values);
  expect(spread(grid.depth.map(({ frontX }) => frontX)))
    .toBeGreaterThan(spread(grid.depth.map(({ rearX }) => rearX)) * 1.8);
});

test("atlas trace follows the original colored strokes without copying its checkerboard", async ({ page }, testInfo) => {
  await startArtwork(page);
  await expect(page.locator(`${ROOT} [data-scene-reference="atlas-row-2-col-1"]`)).toHaveCount(1);
  const comparison = await page.evaluate(async (posterUrl) => {
    const size = 288;
    const decode = async (url: string) => {
      const img = new Image();
      img.src = url;
      await img.decode();
      return img;
    };
    const source = await decode("/imgs/agent-role-icons/scene-designer.png");
    const response = await fetch(posterUrl);
    if (!response.ok) throw new Error(`Poster HTTP ${response.status}`);
    // Undo only the documented static fitting transform, not the traced geometry.
    const svg = (await response.text()).replace('viewBox="0 0 512 512"', 'viewBox="72 60 374.4 374.4"');
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    try {
      const trace = await decode(url);
      const classify = (img: HTMLImageElement) => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = size;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(img, 0, 0, size, size);
        const { data } = ctx.getImageData(0, 0, size, size);
        const labels = new Uint8Array(size * size);
        for (let i = 0; i < labels.length; i += 1) {
          const [r, g, b, a] = data.subarray(i * 4, i * 4 + 4);
          if (a < 128) continue;
          // Gray checkerboard is excluded; compare intrinsic white/blue/gold strokes.
          if (r > 200 && g > 200 && b > 200 && Math.max(r, g, b) - Math.min(r, g, b) < 35) labels[i] = 1;
          else if (b > 120 && b - r > 25 && b - g > 2) labels[i] = 2;
          else if (r > 180 && r - b > 70 && g - b > 45) labels[i] = 3;
        }
        return labels;
      };
      const reference = classify(source);
      const replica = classify(trace);
      // Three source pixels tolerate raster antialiasing and vector stroke edges.
      const coverage = (from: Uint8Array, to: Uint8Array, color: number) => {
        let total = 0;
        let matched = 0;
        for (let i = 0; i < from.length; i += 1) {
          if (from[i] !== color) continue;
          total += 1;
          const x = i % size;
          const y = Math.floor(i / size);
          let found = false;
          for (let dy = -3; dy <= 3 && !found; dy += 1) {
            for (let dx = -3; dx <= 3; dx += 1) {
              const nx = x + dx;
              const ny = y + dy;
              if (dx * dx + dy * dy > 9 || nx < 0 || nx >= size || ny < 0 || ny >= size) continue;
              if (to[ny * size + nx] === color) { found = true; break; }
            }
          }
          if (found) matched += 1;
        }
        return { total, ratio: total ? matched / total : 0 };
      };
      return [1, 2, 3].map((color) => ({
        color, recall: coverage(reference, replica, color), precision: coverage(replica, reference, color),
      }));
    } finally {
      URL.revokeObjectURL(url);
    }
  }, POSTER);
  await testInfo.attach("reference-stroke-coverage", {
    body: JSON.stringify(comparison, null, 2), contentType: "application/json",
  });
  for (const { color, recall, precision } of comparison) {
    expect(recall.total, `Reference color ${color} must exist`).toBeGreaterThan(100);
    expect(precision.total, `Trace color ${color} must exist`).toBeGreaterThan(100);
    expect(recall.ratio, `Reference color ${color} preserved`).toBeGreaterThanOrEqual(0.88);
    expect(precision.ratio, `Trace color ${color} follows the reference`).toBeGreaterThanOrEqual(0.88);
  }
});

for (const dpr of [1, 2]) {
  test(`Scene terminal bitmap matches the original image at 32px DPR ${dpr}`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ deviceScaleFactor: dpr, baseURL });
    const page = await context.newPage();
    try {
      const moduleRequests: string[] = [];
      page.on("request", request => { if (request.url().includes("/roles/SceneDesignerAnimation.tsx")) moduleRequests.push(request.url()); });
      await page.goto("/tests/browser/agent-role-scene-designer-mock.html", { waitUntil: "domcontentloaded" });
      const poster = page.getByTestId("agent-role-static-icon");
      await expect(poster).toHaveAttribute("src", /\/bitmaps-v1\/scene_design-96\.png/);
      await expect.poll(() => poster.evaluate((img) =>
        (img as HTMLImageElement).complete && (img as HTMLImageElement).naturalWidth > 0)).toBe(true);
      const frame = page.getByTestId("agent-role-animation-frame");
      await expect(frame).toHaveCSS("width", "32px");
      const fidelity = await compareBitmapToOriginal(page, POSTER, dpr);
      expect(fidelity.meanChannelDifference).toBeLessThanOrEqual(9);
      expect(fidelity.changedPixelRatio).toBeLessThanOrEqual(0.13);
      expect(fidelity.alphaMismatchRatio).toBeLessThanOrEqual(0.1);
      expect(moduleRequests).toEqual([]);
    } finally {
      await context.close();
    }
  });
}

test("Scene terminal state uses its bitmap without loading artwork", async ({ page }) => {
  const moduleRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("/roles/SceneDesignerAnimation.tsx")) moduleRequests.push(request.url()); });
  await page.route("**/roles/SceneDesignerAnimation.tsx*", (route) => route.abort());
  await page.goto("/tests/browser/agent-role-scene-designer-mock.html");
  await expect(page.locator(ROOT)).toHaveCount(0);
  const poster = page.getByTestId("agent-role-static-icon");
  await expect(poster).toBeVisible();
  await expect(poster).toHaveAttribute("src", /\/bitmaps-v1\/scene_design-96\.png/);
  await expect.poll(() => poster.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  expect(moduleRequests).toEqual([]);
});

test("Scene scanner visibly paints the sun and wider wall silhouette", async ({ page }) => {
  await startArtwork(page);
  const root = page.locator(ROOT);
  await expect(root).toBeVisible();
  const samples = await root.evaluate(async (element) => {
    const results = [];
    for (const offset of [0, 200]) {
      // Rasterize the real artwork in isolation; mask-revealed lines must not
      // falsely count as proof that the separate moving scanner is visible.
      const svg = element.cloneNode(true) as SVGSVGElement;
      svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      svg.setAttribute("width", "512");
      svg.setAttribute("height", "512");
      for (const part of ["construction-scene", "completed-scene"]) {
        svg.querySelector<SVGElement>(`[data-part="${part}"]`)!.style.display = "none";
      }
      const scan = svg.querySelector<SVGElement>('[data-part="scene-scan"]')!;
      scan.style.transform = `translateY(${offset}px)`;
      scan.style.opacity = "1";
      const url = URL.createObjectURL(new Blob([svg.outerHTML], { type: "image/svg+xml" }));
      try {
        const img = new Image();
        img.src = url;
        await img.decode();
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 512;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(img, 0, 0);
        const { data } = ctx.getImageData(0, 0, 512, 512);
        let pixels = 0;
        let left = 512;
        let right = -1;
        let top = 512;
        let bottom = -1;
        for (let i = 0; i < 512 * 512; i += 1) {
          if (data[i * 4 + 3] < 32) continue;
          pixels += 1;
          const x = i % 512;
          const y = Math.floor(i / 512);
          left = Math.min(left, x); right = Math.max(right, x);
          top = Math.min(top, y); bottom = Math.max(bottom, y);
        }
        results.push({ pixels, width: pixels ? right - left + 1 : 0, left, right, top, bottom });
      } finally {
        URL.revokeObjectURL(url);
      }
    }
    return results;
  });
  expect(samples[0].pixels).toBeGreaterThan(100);
  expect(samples[1].pixels).toBeGreaterThan(400);
  expect(samples[1].width).toBeGreaterThan(samples[0].width * 2);
  expect(samples[1].left).toBeGreaterThanOrEqual(86);
  expect(samples[1].right).toBeLessThanOrEqual(430);
  expect(samples[1].top).toBeGreaterThanOrEqual(279);
  expect(samples[1].bottom).toBeLessThanOrEqual(285);
});

test("Scene scan moves through a stationary scene clipping window", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "Scene Designer", exact: true }).click();
  await page.getByRole("button", { name: "Idle", exact: true }).click();
  const root = page.locator(ROOT);
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await page.waitForFunction((selector) => document.querySelector(selector)!
    .getAnimations({ subtree: true }).filter((a) => a.effect!.getTiming().duration === 2600).length === 3, ROOT);
  const window = root.locator('[data-scene-scan-window="true"]');
  await expect(window).toHaveCount(1);
  await expect(window).toHaveAttribute("clip-path", /^url\(#.+\)$/);
  await expect(window.locator(':scope > [data-part="scene-scan"]')).toHaveCount(1);
  expect(await root.locator('[data-part="scene-scan"]').getAttribute("clip-path")).toBeNull();
  const samples = [];
  for (const time of [120, 1100]) {
    samples.push(await root.evaluate((element, currentTime) => {
      element.getAnimations({ subtree: true }).forEach((animation) => {
        animation.pause();
        animation.currentTime = currentTime;
      });
      const matrix = (selector: string) => {
        const m = element.querySelector<SVGGraphicsElement>(selector)!.getCTM()!;
        return [m.a, m.b, m.c, m.d, m.e, m.f];
      };
      return { window: matrix('[data-scene-scan-window="true"]'), line: matrix('[data-part="scene-scan"]') };
    }, time));
  }
  expect(samples[1].window).toEqual(samples[0].window);
  expect(samples[1].line[5] - samples[0].line[5]).toBeGreaterThan(30);
});

test("Scene scan resolves to unfilled linework and cancels on state or reduced motion", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.addStyleTag({
    content: '[data-gallery-role="scene"] .gallery-card__state { display: none !important; }',
  });
  await page.getByRole("button", { name: "Scene Designer", exact: true }).click();
  await page.getByRole("button", { name: "Idle", exact: true }).click();
  const root = page.locator(ROOT);
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
  const idle = await root.screenshot();
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await page.waitForFunction((selector) => {
    const animations = document.querySelector(selector)!.getAnimations({ subtree: true });
    return animations.length === 4 && animations.filter((a) => a.effect!.getTiming().duration === 2600).length === 3;
  }, ROOT);
  for (const time of [120, 1100, 2300]) {
    const state = await root.evaluate((element, currentTime) => {
      element.getAnimations({ subtree: true }).forEach((animation) => {
        animation.pause();
        animation.currentTime = currentTime;
      });
      const transformY = (part: string) =>
        new DOMMatrix(getComputedStyle(element.querySelector(`[data-part="${part}"]`)!).transform).f;
      // Include the shared linework referenced by <use>, but not mask/clip geometry.
      const artworkShapes = [...element.querySelectorAll<SVGGraphicsElement>("path, rect, circle, ellipse, polygon")]
        .filter((shape) => !shape.closest("mask, clipPath"));
      return {
        fills: artworkShapes.map((shape) => getComputedStyle(shape).fill),
        reveal: transformY("scene-reveal"),
        construction: transformY("construction-hide"),
        scan: transformY("scene-scan"),
        glowCount: element.querySelectorAll('[data-part="scene-scan-glow"]').length,
      };
    }, time);
    expect(state.fills.length).toBeGreaterThan(0);
    expect(state.fills.every((fill) => fill === "none")).toBe(true);
    expect(state.glowCount).toBe(0);
    expect(state.reveal).toBeCloseTo(state.construction, 3);
    if (time <= 1940) expect(state.reveal).toBeCloseTo(state.scan, 3);
    if (time === 120) expect(state.reveal).toBeCloseTo(0);
    if (time === 2300) expect(state.reveal).toBeCloseTo(392);
  }
  await page.getByRole("button", { name: "Waiting", exact: true }).click();
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
  expect((await root.screenshot()).equals(idle), "Waiting must match the completed Idle artwork").toBe(true);
  await page.getByRole("button", { name: "Working", exact: true }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => root.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
  expect((await root.screenshot()).equals(idle), "Reduced motion must match the completed Idle artwork").toBe(true);
});
