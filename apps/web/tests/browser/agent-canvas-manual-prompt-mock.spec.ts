import { expect, test } from "@playwright/test";

test("keeps a manually created blank prompt quiet and runs only after its autosave completes", async ({ page }) => {
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html");

  const editor = page.getByLabel("Generation prompt");
  await expect(editor).toBeVisible();
  await expect(page.getByText("Prompt input needed")).toHaveCount(0);
  await expect(page.getByText("Enter a prompt to continue.")).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);

  await editor.fill("A clean studio product shot");
  await page.getByRole("button", { name: "Run image node" }).click();

  await expect.poll(async () => page.getByTestId("manual-prompt-events").textContent()).toContain("patch-start:A clean studio product shot");
  await expect(page.getByTestId("manual-prompt-events")).not.toContainText("run:");
  await expect(page.getByTestId("manual-prompt-events")).toContainText("patch-complete|run:A clean studio product shot");
  await expect(page.getByText("Prompt ready")).toBeVisible();
});

test("keeps a non-empty prompt editable while preparation is not ready", async ({ page }) => {
  for (const preparation of ["queued", "failed", "superseded"] as const) {
    await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?preparation=${preparation}`);

    const editor = page.getByLabel("Generation prompt");
    await expect(editor).toBeVisible();
    await expect(editor).toHaveValue("Existing generation prompt");
    await expect(editor).toBeEnabled();
    await expect(page.getByTestId("manual-node-status")).toHaveText("draft");
    await expect(page.getByLabel("Prompt preparation status")).toBeVisible();
    await expect(page.getByRole("button", { name: "Run image node" })).toBeVisible();
  }
});
