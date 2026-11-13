import { expect, test } from "@playwright/test";

const preview = "/tests/browser/brand-form-confirmation-mock.html";

for (const stage of ["brand-memory", "campaign"]) {
  test(`${stage}: collapses and confirms before a slow submission completes`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${preview}?stage=${stage}&submitDelay=5000`);
    const form = page.getByTestId("brand-form");
    await expect(form).toBeVisible();
    for (const row of await form.getByRole("row").all()) {
      await row.locator("label.agent-chat__brand-form-option").first().click();
    }
    await page.getByRole("button", { name: "确认整张表", exact: true }).click();
    const notice = page.getByRole("status", { name: "信息已确认", exact: true });
    await expect(notice).toBeVisible({ timeout: 500 });
    await expect(form).toBeHidden({ timeout: 500 });
    await expect(page.locator(".agent-chat__interaction-chip")).toContainText("处理中");
    // The timer starts at the click, and a late success must not show the toast again.
    await expect(notice).toBeHidden({ timeout: 3500 });
    await expect(page.locator(".brand-decision-panel")).toContainText(stage === "campaign" ? "新品发布" : "轻量随行水杯");
    await expect(notice).toBeHidden();
    await expect(form).toBeHidden();
  });
}

test("a failed confirmation removes the toast and restores the selected answers", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${preview}?stage=campaign&submitDelay=1500&submitFails=true`);
  const form = page.getByTestId("brand-form");
  await expect(form).toBeVisible();
  for (const row of await form.getByRole("row").all()) {
    await row.locator("label.agent-chat__brand-form-option").first().click();
  }
  await page.getByRole("button", { name: "确认整张表", exact: true }).click();
  const notice = page.getByRole("status", { name: "信息已确认", exact: true });
  await expect(notice).toBeVisible({ timeout: 500 });
  await expect(form).toBeHidden({ timeout: 500 });
  await expect(form).toBeVisible();
  await expect(notice).toBeHidden();
  for (const row of await form.getByRole("row").all()) {
    await expect(row.locator('input[type="radio"]').first()).toBeChecked();
  }
  await expect(page.getByRole("button", { name: "确认整张表", exact: true })).toBeEnabled();
});

for (const stage of ["brand-memory", "campaign"]) {
  test(`${stage}: confirmation has a shrinking gold bar and dismisses after three seconds`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${preview}?stage=${stage}`);
    await expect(page.getByTestId("brand-form")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    for (const row of await page.getByTestId("brand-form").getByRole("row").all()) {
      await row.locator("label.agent-chat__brand-form-option").first().click();
    }
    await page.getByRole("button", { name: "确认整张表", exact: true }).click();
    const notice = page.getByRole("status", { name: "信息已确认", exact: true });
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("已确认的信息可在左侧面板查看。");
    await expect(page.getByText("选择已更新，请检查最新组合。")).toHaveCount(0);
    await expect(page.getByText("This workflow no longer exists.")).toHaveCount(0);
    const bar = notice.locator(".brand-form-confirmation__progress");
    await expect(bar).toHaveCSS("background-color", "rgb(215, 183, 116)");
    await expect(bar).toHaveCSS("animation-duration", "3s");
    const scale = () => bar.evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
    const initialScale = await scale();
    await page.waitForTimeout(900);
    const laterScale = await scale();
    expect(initialScale).toBeGreaterThan(.8);
    expect(laterScale).toBeLessThan(initialScale - .2);
    expect(laterScale).toBeGreaterThan(.4);
    await page.screenshot({ path: `/tmp/adcraft-brand-confirmation-${stage}.png` });
    await expect(notice).toBeHidden({ timeout: 3_000 });
    await expect(page.locator(".brand-decision-panel")).toContainText(stage === "campaign" ? "新品发布" : "轻量随行水杯");
  });
}

test("close button works on a narrow viewport with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(preview);
  await expect(page.getByTestId("brand-form")).toBeVisible();
  for (const row of await page.getByTestId("brand-form").getByRole("row").all()) {
    await row.locator("label.agent-chat__brand-form-option").first().click();
  }
  await page.getByRole("button", { name: "确认整张表", exact: true }).click();
  const notice = page.getByRole("status", { name: "信息已确认", exact: true });
  await expect(notice).toBeVisible();
  const bounds = (await notice.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(16);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(374);
  await page.screenshot({ path: "/tmp/adcraft-brand-confirmation-mobile.png" });
  await notice.getByRole("button", { name: "关闭确认提示" }).click();
  await expect(notice).toBeHidden();
});
