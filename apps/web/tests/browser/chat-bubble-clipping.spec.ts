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

test("Agent avatar is ready with the bubble even when image requests are unavailable", async ({ page }) => {
  await page.route("**/*", route => route.request().resourceType() === "image"
    ? route.abort()
    : route.continue());
  await page.goto(url, { waitUntil: "domcontentloaded" });
  const first = page.locator(item("first"));
  await expect(first.locator(".agent-chat__message-body")).toBeVisible();
  // Check after paint, without polling until a separate image eventually loads.
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  expect(await first.getByRole("img", { name: "AdCraft" }).evaluate(element => {
    const image = element as HTMLImageElement;
    return image.complete && image.naturalWidth > 0;
  })).toBe(true);
});

for (const width of [390, 720]) {
  test(`guided bubbles have no tails and remain inside the paint boundary at width ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 });
    await page.goto(`${url}?guided-only`);
    for (const key of ["guided-short", "guided-long"]) {
      const row = page.locator(item(key));
      await expect(row).toHaveCSS("content-visibility", "auto");
      const question = row.getByRole("article", { name: "Agent question" });
      await expect(question).toHaveCount(1);
      await expect(question).toBeVisible();
      await expect(question).toHaveText("What should this advertisement communicate?");
      await expect(row.locator("details")).not.toHaveAttribute("open");
      for (const bubble of await row.locator(".agent-chat__message-body").all()) {
        await bubble.scrollIntoViewIfNeeded();
        await expect.poll(() => bubble.evaluate(element => {
          const rect = element.getBoundingClientRect();
          const boundary = element.closest(".agent-chat__timeline-virtualized-item")!.getBoundingClientRect();
          return getComputedStyle(element, "::before").content === "none"
            && getComputedStyle(element, "::after").content === "none"
            && rect.top >= boundary.top - 0.1
            && rect.bottom <= boundary.bottom + 0.1;
        })).toBe(true);
      }
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
    // The current conversation layout uses a 22px gap and an 8px continuation inset.
    expect(gaps.compact).toBeCloseTo(14, 0);
    expect(gaps.normal).toBeCloseTo(22, 0);
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
