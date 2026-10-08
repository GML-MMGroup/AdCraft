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
  test(`guided answer tails remain inside the paint boundary at width ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 });
    await page.goto(`${url}?guided-only`);
    for (const key of ["guided-short", "guided-long"]) {
      const row = page.locator(item(key));
      const bubble = row.locator(".agent-chat__guided-answer-bubble .agent-chat__message-body");
      await bubble.scrollIntoViewIfNeeded();
      await expect(row).toHaveCSS("content-visibility", "auto");
      await expect.poll(() => bubble.evaluate(element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const tail = getComputedStyle(element, "::before");
        const tailBottom = rect.bottom - parseFloat(style.borderBottomWidth) - parseFloat(tail.bottom);
        const boundary = element.closest(".agent-chat__timeline-virtualized-item")!.getBoundingClientRect();
        return tail.content !== "none" && parseFloat(tail.borderTopWidth) > 0
          && tailBottom <= boundary.bottom + 0.1;
      })).toBe(true);
      await expect(row.locator(".agent-chat__guided-answer-pair")).toHaveCSS("row-gap", "16px");
    }
  });

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

test("scrolling history preserves complete long replies and bubble painting", async ({ page }) => {
  await page.goto(url);
  const continued = page.locator(item("continued"));
  await expectUnclipped(continued);
  await page.locator(".agent-chat__timeline").evaluate(element => { element.scrollTop = element.scrollHeight; });
  await expect(page.locator(item("history-29"))).toHaveAttribute("data-timeline-hydrated", "true");
  await expectUnclipped(continued);
  const long = page.locator(item("long"));
  const body = long.locator(".agent-chat__message-body");
  await body.scrollIntoViewIfNeeded();
  await expect(long.getByRole("button", { name: /Show more|Show less/ })).toHaveCount(0);
  await expect(body).toHaveCSS("max-height", "none");
  expect(await body.evaluate(element => {
    const content = element.querySelector("p")!;
    return content.textContent?.includes("Line 14:")
      && content.getBoundingClientRect().bottom <= element.getBoundingClientRect().bottom;
  })).toBe(true);
  await expectUnclipped(long);
  await expectUnclipped(continued);
});
