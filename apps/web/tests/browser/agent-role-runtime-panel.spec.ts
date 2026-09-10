import { expect, test, type Locator } from "@playwright/test";

const URL = "/tests/browser/agent-role-runtime-panel-mock.html";
const role = (name: string) => `.agent-chat__stage-thread > header .is-role-${name}`;
async function running(icon: Locator): Promise<boolean> {
  return icon.evaluate(element => [...element.querySelectorAll("svg")]
    .some(svg => svg.getAnimations({ subtree: true }).some(animation =>
      animation.playState === "running" && Number(animation.effect?.getTiming().duration) > 300)));
}

test("real chat panel plays concurrent roles independently and keeps messages singular", async ({ page }) => {
  await page.goto(URL);
  const scene = page.locator(role("scene-design"));
  const character = page.locator(role("character-design"));
  await expect.poll(() => running(scene)).toBe(true);
  await expect.poll(() => running(character)).toBe(true);
  await expect.poll(() => running(page.locator(role("world-setting")))).toBe(false);
  await expect(page.getByText("请同时制作角色和场景。", { exact: true })).toHaveCount(1);
  await expect(page.getByText("角色和场景正在分别制作。", { exact: true })).toHaveCount(1);
  await expect(scene.getByTestId("agent-capability-icon")).toHaveCount(1);
  await expect(character.getByTestId("agent-capability-icon")).toHaveCount(1);
  const box = await scene.getByTestId("agent-role-animation-frame").boundingBox();
  expect(box?.width).toBe(32);
  expect(box?.height).toBe(32);
  await page.getByRole("button", { name: "Scene provider waiting", exact: true }).click();
  await expect(page.getByRole("status", { name: "Scene Designer waiting", exact: true })).toBeVisible();
  await expect.poll(() => running(scene)).toBe(true);
  await expect.poll(() => running(character)).toBe(true);
  await page.getByRole("button", { name: "Complete Scene", exact: true }).click();
  await expect.poll(() => running(scene)).toBe(false);
  await expect.poll(() => running(character)).toBe(true);
  await page.getByRole("button", { name: "Fail Character", exact: true }).click();
  await expect.poll(() => running(character)).toBe(false);
  await page.getByRole("button", { name: "New parallel attempt", exact: true }).click();
  await expect.poll(() => running(scene)).toBe(true);
  await expect.poll(() => running(character)).toBe(true);
});

test("an owning terminal turn stops its role while a queued turn keeps waiting motion", async ({ page }) => {
  await page.goto(URL);
  const scene = page.locator(role("scene-design"));
  const character = page.locator(role("character-design"));
  await expect.poll(() => running(scene)).toBe(true);
  await page.getByRole("button", { name: "Fail Scene turn only", exact: true }).click();
  await expect.poll(() => running(scene)).toBe(false);
  await expect.poll(() => running(character)).toBe(true);
  await page.getByRole("button", { name: "New parallel attempt", exact: true }).click();
  await expect.poll(() => running(scene)).toBe(true);
  await page.getByRole("button", { name: "Queue Scene turn only", exact: true }).click();
  await expect(scene.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "waiting");
  await expect.poll(() => scene.evaluate(element => element.getAnimations({ subtree: true }).some(animation => animation.playState === "running"))).toBe(true);
  await expect.poll(() => running(character)).toBe(true);
});

test("native role clocks advance and actual panel unmount cancels owned animations", async ({ page }) => {
  await page.goto(URL);
  const scene = page.locator(role("scene-design"));
  await expect.poll(() => scene.evaluate(element => element.getAnimations({ subtree: true })
    .filter(animation => animation.effect?.getTiming().duration === 2600).length)).toBe(3);
  const times = await scene.evaluate(async element => {
    const animations = element.getAnimations({ subtree: true });
    const before = animations.map(animation => Number(animation.currentTime));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return animations.map((animation, index) => Number(animation.currentTime) - before[index]!);
  });
  expect(times.every(delta => delta > 0)).toBe(true);
  const owned = await scene.evaluateHandle(element => element.getAnimations({ subtree: true }));
  await page.getByRole("button", { name: "Unmount panel", exact: true }).click();
  await expect.poll(() => owned.evaluate(animations => animations.every(animation => animation.playState === "idle"))).toBe(true);
  await owned.dispose();
  await expect(page.getByRole("complementary", { name: "AdCraft Video Agent" })).toHaveCount(0);
});

test("real panel honors reduced motion before load and on live preference changes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(URL);
  const scene = page.locator(role("scene-design"));
  await expect(scene.locator("svg")).toHaveCount(1);
  await expect.poll(() => running(scene)).toBe(false);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect.poll(() => running(scene)).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => scene.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
});

test("a failed artwork chunk retains the static role without blocking another role", async ({ page }) => {
  await page.route("**/roles/SceneDesignerAnimation.tsx*", route => route.abort());
  await page.goto(URL);
  const scene = page.locator(role("scene-design"));
  await expect(scene.getByTestId("agent-role-static-icon")).toBeVisible();
  await expect.poll(() => scene.getByTestId("agent-role-static-icon").evaluate(image =>
    image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0)).toBe(true);
  await expect.poll(() => running(page.locator(role("character-design")))).toBe(true);
  await expect(scene.locator("svg")).toHaveCount(0);
  await expect(page.getByText("Conversation could not be refreshed")).toHaveCount(0);
});

test("all ten approved roles play inside real stage headers and settle on completion", async ({ page }) => {
  await page.goto(URL);
  await page.getByRole("button", { name: "Run all ten roles", exact: true }).click();
  const names = ["world-setting", "product-design", "prop-design", "character-design", "scene-design",
    "script-authoring", "storyboard-design", "video-direction", "bgm-direction", "quick-media"];
  for (const name of names) {
    const icon = page.locator(role(name));
    await icon.scrollIntoViewIfNeeded();
    await expect.poll(() => running(icon)).toBe(true);
    await expect(icon.getByTestId("agent-capability-icon")).toHaveCount(1);
  }
  await page.getByRole("button", { name: "Complete all", exact: true }).click();
  for (const name of names) await expect.poll(() => running(page.locator(role(name)))).toBe(false);
});

test("queued roles including empty waiting artwork keep gentle motion and release it", async ({ page }) => {
  await page.goto(URL);
  await page.getByRole("button", { name: "Run all ten roles", exact: true }).click();
  await page.getByRole("button", { name: "Queue all roles", exact: true }).click();
  const world = page.locator(role("world-setting"));
  await world.scrollIntoViewIfNeeded();
  await expect(world.getByTestId("agent-role-animation-frame")).toHaveAttribute("data-motion-state", "waiting");
  await expect.poll(() => world.evaluate(element => element.getAnimations({ subtree: true })
    .some(animation => animation.playState === "running" && animation.effect?.getTiming().duration === 1800))).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => world.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect.poll(() => world.evaluate(element => element.getAnimations({ subtree: true }).length)).toBeGreaterThan(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => world.evaluate(element => element.getAnimations({ subtree: true }).every(animation => animation.playState === "paused"))).toBe(true);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.getByRole("button", { name: "Complete all", exact: true }).click();
  await expect(world.locator("img")).toHaveCount(1);
  await expect(world.locator("svg")).toHaveCount(0);
  await expect.poll(() => world.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
});
