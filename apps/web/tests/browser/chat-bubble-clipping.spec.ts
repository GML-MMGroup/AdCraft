import { expect, test, type Locator } from "@playwright/test";

const url = "/tests/browser/chat-bubble-clipping-mock.html";
const item = (key: string) => `[data-timeline-key="${key}"]`;

async function expectUnclipped(row: Locator) {
  const bubble = row.locator(".agent-chat__message-body");
  await bubble.scrollIntoViewIfNeeded();
  await expect.poll(() => bubble.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const parent = element.closest(".agent-chat__timeline-virtualized-item")!;
    const topInside = rect.top >= parent.getBoundingClientRect().top - 0.1;
    const topPainted = [2, 4, 6].every(offset => element.contains(
      document.elementFromPoint(rect.x + rect.width / 2, rect.top + offset),
    ));
    return topInside && topPainted;
  })).toBe(true);
  await expect(row).toHaveCSS("content-visibility", "auto");
}

for (const width of [390, 720]) {
  test(`continuous bubble keeps its top and compact spacing at width ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 });
    await page.goto(url);
    await expectUnclipped(page.locator(item("continued")));
    const gaps = await page.evaluate(() => {
      const rect = (key: string) => document.querySelector(`[data-timeline-key="${key}"]`)!.getBoundingClientRect();
      return { compact: rect("continued").top - rect("first").bottom, normal: rect("user").top - rect("continued").bottom };
    });
    expect(gaps.compact).toBeCloseTo(8, 0);
    expect(gaps.normal).toBeCloseTo(16, 0);
    await expect(page.locator(`${item("continued")} article`)).toHaveCSS("margin-top", "0px");
  });
}

test("a continuation displayed first stays within the first item boundary", async ({ page }) => {
  await page.goto(`${url}?first-only`);
  const first = page.locator(item("continued"));
  await expectUnclipped(first);
  await expect(first).toHaveCSS("margin-top", "0px");
});

test("scrolling history and expanding a long reply preserve bubble painting", async ({ page }) => {
  await page.goto(url);
  const continued = page.locator(item("continued"));
  await expectUnclipped(continued);
  await page.locator(".agent-chat__timeline").evaluate(element => { element.scrollTop = element.scrollHeight; });
  await expect(page.locator(item("history-29"))).toHaveAttribute("data-timeline-hydrated", "true");
  await expectUnclipped(continued);
  const long = page.locator(item("long"));
  await long.getByRole("button", { name: "Show more" }).click();
  await expect(long.locator(".agent-chat__message-body")).toHaveClass(/is-expanded/);
  await expectUnclipped(long);
  await long.getByRole("button", { name: "Show less" }).click();
  await expect(long.locator(".agent-chat__message-body")).toHaveClass(/is-collapsed/);
  await expectUnclipped(continued);
});
