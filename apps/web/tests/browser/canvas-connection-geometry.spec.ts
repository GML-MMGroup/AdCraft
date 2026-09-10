import { expect, test, type Locator, type Page } from "@playwright/test";

const preview = ".agent-canvas-connection-line";
const node = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
const handle = (page: Page, id: string, side: "input" | "output") => node(page, id).locator(`.agent-canvas-node__handle--${side}`);

async function center(locator: Locator) {
  const rect = await locator.boundingBox();
  expect(rect).not.toBeNull();
  return { x: rect!.x + rect!.width / 2, y: rect!.y + rect!.height / 2 };
}

async function border(page: Page, id: string, side: "left" | "right") {
  const rect = await node(page, id).locator(".agent-canvas-node").boundingBox();
  expect(rect).not.toBeNull();
  return { x: rect!.x + (side === "right" ? rect!.width : 0), y: rect!.y + rect!.height / 2 };
}

async function endpoint(locator: Locator, end: boolean) {
  return locator.evaluate((element, end) => {
    const path = element as SVGPathElement;
    const point = path.getPointAtLength(end ? path.getTotalLength() : 0);
    const screen = new DOMPoint(point.x, point.y).matrixTransform(path.getScreenCTM()!);
    return { x: screen.x, y: screen.y };
  }, end);
}

async function expectPoint(locator: Locator, end: boolean, point: { x: number; y: number }) {
  await expect.poll(async () => {
    const actual = await endpoint(locator, end);
    return Math.hypot(actual.x - point.x, actual.y - point.y);
  }).toBeLessThan(1);
}

async function open(page: Page, zoom: number, shape = "square") {
  await page.setViewportSize({ width: 1800, height: 1300 });
  await page.route("**/api/v2/**", (route) => route.request().url().includes("connection-fixture/preview")
    ? route.fulfill({ path: "public/brand/adcraft-icon.webp", contentType: "image/webp" })
    : route.abort());
  await page.goto(`/tests/browser/canvas-connection-geometry-mock.html?zoom=${zoom}&shape=${shape}`);
  await expect(node(page, "source").locator("img")).toBeVisible();
  await expect.poll(() => node(page, "source").locator("img").evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
}

for (const zoom of [0.5, 1, 1.5]) {
  for (const shape of ["square", "landscape", "portrait"]) {
    test(`preview and permanent edge meet card borders: ${shape}, zoom ${zoom}`, async ({ page }) => {
      await open(page, zoom, shape);
      const source = await center(handle(page, "source", "output"));
      const target = await center(handle(page, "target", "input"));
      const sourceBorder = await border(page, "source", "right");
      const targetBorder = await border(page, "target", "left");
      expect(Math.abs((source.x - sourceBorder.x) / zoom - 12)).toBeLessThan(0.1);
      expect(Math.abs((targetBorder.x - target.x) / zoom - 12)).toBeLessThan(0.1);

      // Center and off-center hits both use the real Handle, not a synthesized connection.
      await page.mouse.move(source.x, source.y + (shape === "portrait" ? 16 * zoom : 0));
      await expect(handle(page, "source", "output")).toHaveCSS("opacity", "1");
      await page.mouse.down();
      const pointer = { x: Math.round(source.x + 65 * zoom), y: Math.round(source.y - 70 * zoom) };
      await page.mouse.move(pointer.x, pointer.y, { steps: 5 });
      await expect(page.locator(preview)).toBeVisible();
      await expectPoint(page.locator(preview), false, sourceBorder);
      await expectPoint(page.locator(preview), true, pointer);

      // Outside both the 40px hit box and the 24px magnet radius, keep following the pointer.
      const outside = { x: Math.round(target.x - 30 * zoom), y: Math.round(target.y) };
      await page.mouse.move(outside.x, outside.y, { steps: 5 });
      await expect(page.locator(preview)).not.toHaveAttribute("data-connection-status", "valid");
      await expectPoint(page.locator(preview), true, outside);

      // 22px is outside the hit box but within the magnet radius.
      await page.mouse.move(target.x - 22 * zoom, target.y, { steps: 5 });
      await expect(page.locator(preview)).toHaveAttribute("data-connection-status", "valid");
      await expectPoint(page.locator(preview), false, sourceBorder);
      await expectPoint(page.locator(preview), true, targetBorder);
      if (zoom === 1) await page.screenshot({ path: `/tmp/canvas-connection-${shape}-snapped.png` });
      await page.mouse.up();
      await expect(page.getByTestId("submits")).toHaveText("1");
      await expect(page.locator(preview)).toHaveCount(0);
      const edge = page.locator(".react-flow__edge-path");
      await expect(edge).toHaveCount(1);
      await expectPoint(edge, false, sourceBorder);
      await expectPoint(edge, true, targetBorder);
    });
  }
}

test("invalid targets never snap or submit; reverse drags use the same border geometry", async ({ page }) => {
  await open(page, 1);
  const source = await center(handle(page, "source", "output"));
  const invalid = await center(handle(page, "invalid", "input"));
  await page.mouse.move(source.x, source.y);
  await page.mouse.down();
  await page.mouse.move(invalid.x, invalid.y, { steps: 8 });
  await expect(page.locator(preview)).toHaveAttribute("data-connection-status", "invalid");
  await expectPoint(page.locator(preview), true, invalid);
  await page.mouse.up();
  await expect(page.getByTestId("submits")).toHaveText("0");
  await expect(page.locator(".react-flow__edge-path")).toHaveCount(0);

  const target = await center(handle(page, "target", "input"));
  await page.mouse.move(target.x, target.y);
  await page.mouse.down();
  await page.mouse.move(source.x, source.y, { steps: 8 });
  await expect(page.locator(preview)).toHaveAttribute("data-connection-status", "valid");
  await expectPoint(page.locator(preview), false, await border(page, "target", "left"));
  await expectPoint(page.locator(preview), true, await border(page, "source", "right"));
  await page.mouse.up();
  await expect(page.getByTestId("submits")).toHaveText("1");
  const edge = page.locator(".react-flow__edge-path");
  await expectPoint(edge, false, await border(page, "source", "right"));
  await expectPoint(edge, true, await border(page, "target", "left"));
});
