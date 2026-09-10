import { expect, test } from "@playwright/test";

test("updates only affected graph items for Runtime and selection changes", async ({ page }) => {
  await page.goto("/tests/browser/agent-canvas-incremental-graph-mock.html");

  await page.getByRole("button", { name: "Runtime update" }).click();
  await expect(page.getByTestId("node-replacements")).toHaveText("1");
  await expect(page.getByTestId("edge-replacements")).toHaveText("0");
  await expect(page.getByTestId("node-snapshot-reused")).toHaveText("false");
  await expect(page.getByTestId("edge-snapshot-reused")).toHaveText("true");

  await page.getByRole("button", { name: "Runtime no-op" }).click();
  await expect(page.getByTestId("node-replacements")).toHaveText("0");
  await expect(page.getByTestId("node-snapshot-reused")).toHaveText("true");

  await page.getByRole("button", { name: "Select video" }).click();
  await expect(page.getByTestId("edge-replacements")).toHaveText("2");

  await page.getByRole("button", { name: "Select image" }).click();
  await expect(page.getByTestId("edge-replacements")).toHaveText("1");
  await expect(page.getByTestId("node-snapshot-reused")).toHaveText("true");
});
