import { expect, test } from "@playwright/test";

const URL = "/tests/browser/agent-role-lifecycle-mock.html";
const character = ".agent-chat__stage-thread > header .is-role-character-design";

test("live detail completion stops artwork without reloading or changing presentation revision", async ({ page }) => {
  await page.goto(`${URL}?live-detail-refresh`);
  const role = page.locator(character);
  const frame = role.getByTestId("agent-role-animation-frame");
  await expect(frame).toHaveAttribute("data-motion-state", "working");
  await expect(role.locator("svg")).toBeVisible();
  // The same thread/frame must survive each detail refresh.
  await frame.evaluate(element => element.setAttribute("data-live-identity", "original"));
  for (const terminal of ["Media success", "failed", "superseded"]) {
    await page.getByRole("button", { name: terminal, exact: true }).click();
    await expect(frame).toHaveAttribute("data-motion-state", "idle");
    await expect(frame).toHaveAttribute("data-live-identity", "original");
    await expect(role.locator("img")).toBeVisible();
    await expect(role.locator("svg")).toHaveCount(0);
    await page.getByRole("button", { name: "Retry task", exact: true }).click();
    await expect(frame).toHaveAttribute("data-motion-state", "working");
    await expect(role.locator("svg")).toBeVisible();
  }
});

test("later queued planning inherits task completion, failure and retry without keeping artwork alive", async ({ page }) => {
  await page.goto(`${URL}?planning-progress`);
  const role = page.locator(character);
  const frame = role.getByTestId("agent-role-animation-frame");
  await expect(frame).toHaveAttribute("data-motion-state", "working");
  for (const terminal of ["Media success", "failed", "cancelled", "superseded"]) {
    await page.getByRole("button", { name: terminal, exact: true }).click();
    await expect(frame).toHaveAttribute("data-motion-state", "idle");
    await expect(role.locator("img")).toBeVisible();
    await expect(role.locator("svg")).toHaveCount(0);
    await page.getByRole("button", { name: "Retry task" }).click();
    await expect(frame).toHaveAttribute("data-motion-state", "working");
    await expect(role.locator("svg")).toBeVisible();
  }
});

test("prompt and media intermediate states do not stop motion; explicit role completion does", async ({ page }) => {
  await page.goto(URL);
  const role = page.locator(character);
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");
  await expect(page.getByTestId("lifecycle-evidence")).toHaveText("timeline");

  await page.getByRole("button", { name: "Prompt ready draft" }).click();
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");
  await page.getByRole("button", { name: "Media working" }).click();
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");
  await expect(page.getByTestId("lifecycle-evidence")).toHaveText("timeline");
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
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("working");
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "working");

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
  await expect(page.getByTestId("lifecycle-phase")).toHaveText("completed");
  await expect(role.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "idle");
});
