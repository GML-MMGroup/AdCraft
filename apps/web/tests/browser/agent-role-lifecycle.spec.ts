import { expect, test } from "@playwright/test";

const URL = "/tests/browser/agent-role-lifecycle-mock.html";
const character = ".agent-chat__stage-thread > header .is-role-character-design";

test("materialization completion yields to prompt, draft, media, and persisted success authority", async ({ page }) => {
  await page.goto(URL);
  const role = page.locator(character);
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");
  await expect(page.getByTestId("lifecycle-evidence")).toHaveText("prompt_preparation");

  await page.getByRole("button", { name: "Prompt ready draft" }).click();
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "waiting");
  await page.getByRole("button", { name: "Media working" }).click();
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");
  await expect(page.getByTestId("lifecycle-evidence")).toHaveText("node_runtime");
  await page.getByRole("button", { name: "Media success" }).click();
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "idle");
  await expect(role.locator("img")).toBeVisible();
  await expect(role.locator("svg")).toHaveCount(0);
});

test("terminal outcomes stop motion and a retry creates a new working task", async ({ page }) => {
  await page.goto(URL);
  const role = page.locator(character);
  for (const [index, outcome] of (["failed", "cancelled", "superseded"] as const).entries()) {
    await page.getByRole("button", { name: outcome }).click();
    await expect(page.getByTestId("lifecycle-phase")).toHaveText(outcome);
    await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "idle");
    await page.getByRole("button", { name: "Retry task" }).click();
    await expect(page.getByTestId("lifecycle-attempt")).toHaveText(new RegExp(`:${index + 2}$`));
    await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");
  }
});

test("three character occurrences keep Main and Turnaround state independent", async ({ page }) => {
  await page.goto(URL);
  const role = page.locator(character);
  await page.getByRole("button", { name: "Media success" }).click();
  await page.getByRole("button", { name: "Occurrence 2 Turnaround" }).click();
  await expect(page.getByTestId("lifecycle-occurrence")).toHaveText("character-2");
  await expect(page.getByTestId("lifecycle-character-phase")).toHaveText("turnaround");
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("failed");
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "idle");

  await page.getByRole("button", { name: "Occurrence 2 Main" }).click();
  await expect(page.getByTestId("lifecycle-occurrence")).toHaveText("character-2");
  await expect(page.getByTestId("lifecycle-character-phase")).toHaveText("main");
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("queued");
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "waiting");

  await page.getByRole("button", { name: "Occurrence 2 Turnaround" }).click();
  await expect(page.getByTestId("lifecycle-character-phase")).toHaveText("turnaround");
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("failed");

  await page.getByRole("button", { name: "Occurrence 3 Main" }).click();
  await expect(page.getByTestId("lifecycle-occurrence")).toHaveText("character-3");
  await expect(page.getByTestId("lifecycle-character-phase")).toHaveText("main");
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("working");
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");

  await page.getByRole("button", { name: "Occurrence 1 Main" }).click();
  await expect(page.getByTestId("lifecycle-occurrence")).toHaveText("character-1");
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("succeeded");
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "idle");
});
