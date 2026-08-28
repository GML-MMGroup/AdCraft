import { expect, test } from "@playwright/test";

test("navigates between structured conversation results and canvas nodes", async ({ page }) => {
  await page.goto("/tests/browser/agent-conversation-canvas-links-mock.html");

  await page.getByRole("button", { name: "View on canvas" }).first().click();
  await expect(page.locator('[data-node-id="storyboard-1"]')).toHaveClass(/is-conversation-highlighted/);
  await expect(page.locator('[data-node-id="video-1"]')).toHaveClass(/is-conversation-highlighted/);
  await expect(page.getByTestId("editor-state")).toHaveText("No node editor opened");

  await page.locator('[data-node-id="storyboard-1"]').click();
  await page.getByRole("button", { name: "Collapse" }).click();
  await page.getByRole("button", { name: "Show in conversation" }).click();

  const source = page.locator('[data-conversation-location="stage:storyboard_design"]');
  await expect(page.getByRole("complementary", { name: "AdCraft Video Agent" })).toBeVisible();
  await expect(source).toHaveClass(/is-highlighted/);
  await expect(source).toBeFocused();
  await expect(page.getByText("Created from the selected storyboard direction.")).toBeVisible();
});
