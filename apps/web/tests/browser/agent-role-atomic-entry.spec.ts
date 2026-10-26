import { expect, test } from "@playwright/test";

const fixture = "/tests/browser/agent-role-runtime-panel-mock.html?hold-artwork";
const identity = ".agent-chat__stage-thread > header .is-role-scene-design";

test("pending artwork gates all role copy; text and playing artwork enter together", async ({ page }) => {
  await page.addInitScript(() => {
    Object.assign(window, { bareRoleFrames: 0 });
    const sample = () => {
      const role = document.querySelector(".agent-chat__stage-thread > header .is-role-scene-design");
      if (role?.querySelector("strong") && !role.querySelector("svg")) {
        const state = window as unknown as { bareRoleFrames: number };
        state.bareRoleFrames++;
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await page.goto(fixture);
  const panel = page.getByRole("complementary", { name: "AdCraft Video Agent" });
  const placeholder = panel.locator(".agent-chat__stage-thread--loading");
  await expect(placeholder).toHaveCount(1);
  await expect(placeholder.getByText("Working", { exact: true })).toBeVisible();
  await expect(placeholder.locator('[data-variant="halo"]')).toHaveCount(1);
  await expect(panel.getByText("Scene Designer", { exact: true })).toHaveCount(0);
  await expect(placeholder.locator("img")).toHaveCount(0);
  // Cross the resource timeout too: a slow module must not show a bitmap.
  await page.waitForTimeout(1650);
  await expect(placeholder).toBeVisible();
  await page.getByRole("button", { name: "Release artwork", exact: true }).click();
  const role = page.locator(identity);
  await expect(role.getByText("Scene Designer", { exact: true })).toBeVisible();
  await expect(role.locator("svg")).toHaveCount(1);
  await expect(role.locator("img")).toHaveCount(0);
  await expect.poll(() => role.evaluate(element =>
    element.getAnimations({ subtree: true }).some(animation =>
      animation.playState === "running" && animation.effect?.getTiming().iterations === Infinity))).toBe(true);
  expect(await page.evaluate(() => (window as unknown as { bareRoleFrames: number }).bareRoleFrames)).toBe(0);
});

test("terminal arriving during loading skips animation and stays terminal after late ready", async ({ page }) => {
  await page.goto(fixture);
  await expect(page.locator(".agent-chat__stage-thread--loading")).toHaveCount(1);
  await page.getByRole("button", { name: "Complete Scene", exact: true }).click();
  const role = page.locator(identity);
  await expect(role.locator("img")).toHaveCount(1);
  await page.getByRole("button", { name: "Release artwork", exact: true }).click();
  await expect(role.locator("svg")).toHaveCount(0);
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "idle");
});

test("resource failure offers bounded retry without leaking role text or static artwork", async ({ page }) => {
  await page.goto(fixture);
  await page.getByRole("button", { name: "Fail artwork", exact: true }).click();
  const alert = page.getByRole("alert").filter({ hasText: "Role animation could not be loaded." });
  await expect(alert).toBeVisible();
  await expect(page.locator(identity)).toHaveCount(0);
  await expect(alert.locator("img")).toHaveCount(0);
  await alert.getByRole("button", { name: "Retry animation" }).click();
  await expect(page.locator(identity).locator("svg")).toHaveCount(1);
});
