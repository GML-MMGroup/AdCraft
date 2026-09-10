import { expect, test } from "@playwright/test";

interface AnimationSnapshot {
  cssTransitionCount: number;
  roleWaapiCount: number;
  totalAnimationCount: number;
  transitionDurationsMs: number[];
  transitionDuration: string;
  transitionProperty: string;
}

interface ReducedMotionProbe {
  isReady(): boolean;
  snapshot(): AnimationSnapshot;
  swapAssets(): Promise<AnimationSnapshot>;
}

test("reduced motion before load keeps PNG/SVG handoff and role artwork still", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/tests/browser/agent-role-reduced-motion-mock.html");
  await page.waitForFunction(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.isReady()
  ));

  const beforeSwap = await page.evaluate(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.snapshot()
  ));
  expect(beforeSwap.transitionProperty).toBe("none");
  expect(beforeSwap.transitionDuration).toBe("0s");
  expect(beforeSwap.roleWaapiCount).toBe(0);
  expect(beforeSwap.totalAnimationCount).toBe(0);

  const afterSwap = await page.evaluate(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.swapAssets()
  ));
  expect(afterSwap.cssTransitionCount).toBe(0);
  expect(afterSwap.roleWaapiCount).toBe(0);
  expect(afterSwap.totalAnimationCount).toBe(0);
});

test("live reduced-motion change cancels role WAAPI and later asset handoffs", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/tests/browser/agent-role-reduced-motion-mock.html");
  await page.waitForFunction(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.isReady()
  ));
  await page.waitForFunction(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.snapshot().roleWaapiCount > 0
  ));

  const normalHandoff = await page.evaluate(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.swapAssets()
  ));
  expect(normalHandoff.transitionProperty).toBe("opacity");
  expect(normalHandoff.transitionDuration).toBe("0.12s");
  expect(normalHandoff.cssTransitionCount).toBe(2);
  expect(normalHandoff.transitionDurationsMs).toEqual([120, 120]);
  expect(normalHandoff.roleWaapiCount).toBeGreaterThan(0);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForFunction(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.snapshot().totalAnimationCount === 0
  ));
  const reducedHandoff = await page.evaluate(() => (
    (window as unknown as { agentRoleReducedMotionProbe: ReducedMotionProbe })
      .agentRoleReducedMotionProbe.swapAssets()
  ));

  expect(reducedHandoff.transitionProperty).toBe("none");
  expect(reducedHandoff.transitionDuration).toBe("0s");
  expect(reducedHandoff.cssTransitionCount).toBe(0);
  expect(reducedHandoff.roleWaapiCount).toBe(0);
  expect(reducedHandoff.totalAnimationCount).toBe(0);
});
