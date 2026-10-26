import { expect, test } from "@playwright/test";

const nodeTypes = ["image", "video", "audio", "text", "script"] as const;

for (const nodeType of nodeTypes) {
  test(`${nodeType} prompt preparation uses the shared inline loop`, async ({ page }) => {
    await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?promptPreparing=${nodeType}`);

    const overlay = page.getByText("提示词正在准备...", { exact: true });
    await expect(overlay).toHaveClass(/agent-node-workbench__preparing-prompt/);
    await expect(page.getByRole("textbox")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByLabel("Prompt preparation status")).toHaveCount(0);

    const animationState = await overlay.evaluate((element) => ({
      animations: element.getAnimations().length,
      bounds: element.getBoundingClientRect().toJSON(),
      editor: element.parentElement?.getBoundingClientRect().toJSON(),
    }));
    expect(animationState.animations).toBe(1);
    expect(animationState.bounds.width).toBeLessThanOrEqual(animationState.editor.width);
    expect(animationState.bounds.height).toBeLessThanOrEqual(animationState.editor.height);

    await page.getByRole("button", { name: "Mark prompt ready" }).click();
    await expect(overlay).toHaveCount(0);
    await expect(page.getByRole("textbox")).toHaveValue("Prepared generation prompt");
  });
}

test("reduced motion keeps the full preparation copy without a running loop", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?promptPreparing=image");

  const overlay = page.getByText("提示词正在准备...", { exact: true });
  await expect(overlay).toBeVisible();
  await expect.poll(() => overlay.evaluate(element => element.getAnimations().length)).toBe(0);
  await expect(page.getByRole("textbox")).toHaveAttribute("aria-busy", "true");
});

test("typing real input immediately removes the preparation overlay and saves only user text", async ({ page }) => {
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?promptPreparing=script");

  const editor = page.getByRole("textbox");
  await editor.fill("A user-authored script direction.");
  await expect(page.getByText("提示词正在准备...", { exact: true })).toHaveCount(0);
  await expect(editor).toHaveAttribute("aria-busy", "false");
  await expect(page.getByTestId("manual-prompt-events")).toContainText("patch-start:A user-authored script direction.");
  await expect(page.getByTestId("manual-prompt-events")).not.toContainText("提示词正在准备");
});
