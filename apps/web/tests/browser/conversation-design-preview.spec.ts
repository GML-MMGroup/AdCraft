import { expect, test } from "@playwright/test";

const preview = "/tests/browser/conversation-design-mock.html";

test("a direction becomes one expandable receipt and settles after generation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  const apiRequests: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url());
  });
  await page.goto(preview);
  const dock = page.locator(".agent-chat__decision-dock--concept");
  const question = page.getByRole("article", { name: "助手提问", exact: true });
  const questionText = "你更想用哪一种方式，讲述这只水杯的故事？";
  await expect(question).toHaveCount(1);
  await expect(question).toContainText(questionText);
  const body = dock.locator(".agent-chat__decision-dock-body");
  await expect(dock.getByRole("radio")).toHaveCount(5);
  const bodyBox = await body.boundingBox();
  for (let index = 0; index < 4; index += 1) {
    const box = await dock.getByRole("radio").nth(index).boundingBox();
    expect(box!.y).toBeGreaterThanOrEqual(bodyBox!.y);
    expect(box!.y + box!.height).toBeLessThanOrEqual(bodyBox!.y + bodyBox!.height + 1);
  }
  const confirm = page.getByRole("button", { name: "确认方向", exact: true });
  await expect(confirm).toBeDisabled();
  await dock.getByRole("radio", { name: /让生活，慢半拍/ }).click();
  await expect(confirm).toBeEnabled();
  await expect(confirm).toBeInViewport();
  await confirm.click();
  await expect(page.getByRole("button", { name: "生成中", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(dock).toHaveCount(0);
  const receipt = page.locator(".agent-chat__selection-receipt").filter({ hasText: "让生活，慢半拍" });
  await expect(receipt).toHaveCount(1);
  await expect(receipt.locator("details")).not.toHaveAttribute("open");
  await expect(receipt.locator("summary strong")).toHaveText("创意假设");
  await expect(receipt.getByText("让生活，慢半拍", { exact: true })).toBeHidden();
  await expect(question).toHaveCount(1);
  await expect(question.getByText(questionText, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "已确认", exact: true })).toHaveAttribute("aria-pressed", "true", { timeout: 8000 });
  await expect(page.locator(".agent-chat").getByText("故事节奏", { exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "agent正在工作中...", exact: true })).toHaveCount(0);
  await expect(receipt).toHaveCount(1);
  await receipt.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(receipt.getByText("让生活，慢半拍", { exact: true })).toBeVisible();
  await expect(receipt.getByText("你更想用哪一种方式，讲述这只水杯的故事？", { exact: true })).toHaveCount(0);
  await page.goto(`${preview}?state=confirmed`);
  await expect(receipt.locator("summary strong")).toHaveText("创意假设");
  await expect(receipt.getByText("让生活，慢半拍", { exact: true })).toBeHidden();
  await expect(question).toHaveCount(1);
  await expect(question.getByText(questionText, { exact: true })).toBeVisible();
  await page.reload();
  await expect(question).toHaveCount(1);
  await expect(question.getByText(questionText, { exact: true })).toBeVisible();
  expect(apiRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test("completed brand decisions disclose their content using the keyboard", async ({ page }) => {
  await page.goto(`${preview}?state=confirmed`);
  const receipt = page.locator(".agent-chat__selection-receipt").filter({ hasText: "品牌记忆" });
  const detail = receipt.getByText("轻量随行水杯", { exact: true });
  await expect(detail).toBeHidden();
  await receipt.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(detail).toBeVisible();
  await page.keyboard.press("Space");
  await expect(detail).toBeHidden();
});

test("preview scenarios reset the panel without retaining busy state", async ({ page }) => {
  await page.goto(`${preview}?state=working`);
  await expect(page.getByRole("status", { name: "agent正在工作中...", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "已确认", exact: true }).click();
  await expect(page.locator(".agent-chat").getByText("故事节奏", { exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "agent正在工作中...", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "选择方向", exact: true }).click();
  await expect(page.getByRole("button", { name: "确认方向", exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "agent正在工作中...", exact: true })).toHaveCount(0);
});

for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 640 }]) {
  test(`choice actions remain reachable at ${viewport.width} × ${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(preview);
    const confirm = page.getByRole("button", { name: "确认方向", exact: true });
    await expect(confirm).toBeInViewport();
    await expect(page.locator(".agent-chat__composer textarea")).toBeInViewport();
    const option = page.locator(".agent-chat__decision-dock--concept").getByRole("radio", { name: /从一杯水开始/ });
    await option.click();
    await expect(option).toHaveAttribute("aria-checked", "true");
    await expect(confirm).toBeEnabled();
    await expect(confirm).toBeInViewport();
    const fit = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth <= innerWidth,
      panel: [...document.querySelectorAll(".agent-chat, .agent-chat__decision-dock-body")]
        .every(element => element.scrollWidth <= element.clientWidth + 1),
    }));
    expect(fit).toEqual({ document: true, panel: true });
  });
}
