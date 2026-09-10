import { expect, test } from "@playwright/test";

interface EntryProbeResult {
  activePart: string;
  maxOpacityDelta: number;
  maxRotationDelta: number;
  maxScaleXDelta: number;
  maxScaleYDelta: number;
  maxTranslationFinalPx: number;
  role: string;
  sampleTimeMs: number;
}

interface ContinuityProbeResult {
  maxMatrixDelta: number;
  maxOpacityDelta: number;
  maxScaleXDelta: number;
  maxScaleYDelta: number;
  role: string;
}

interface LoopStartObservation {
  entryAnimationCount: number;
  expectedPhaseMs: number;
  loopCount: number;
  maxInitialPhaseDeltaMs: number;
  maxObservedPhaseMs: number;
  minObservedPhaseMs: number;
  role: string;
}

interface EntryProbe {
  compareEntryAndLoopPose(role: string): Promise<ContinuityProbeResult>;
  observeLoopStart(role: string): Promise<LoopStartObservation>;
  roleNames: string[];
  sampleRole(role: string, sampleTimeMs?: number): EntryProbeResult;
}

test("role entry samples are native, bounded, continuous, and perceptible where corrected", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-entry-seam-mock.html");
  await page.waitForFunction(() => "agentRoleEntryProbe" in window);
  const roleNames = await page.evaluate(() => (
    (window as unknown as { agentRoleEntryProbe: EntryProbe }).agentRoleEntryProbe.roleNames
  ));
  const entries = await page.evaluate((roles) => {
    const probe = (window as unknown as { agentRoleEntryProbe: EntryProbe }).agentRoleEntryProbe;
    return roles.map((role) => probe.sampleRole(role));
  }, roleNames);

  for (const entry of entries) {
    const noncanonical = entry.maxTranslationFinalPx >= 0.01
      || entry.maxRotationDelta >= 0.01
      || entry.maxScaleXDelta >= 0.0001
      || entry.maxScaleYDelta >= 0.0001
      || entry.maxOpacityDelta >= 0.01;
    expect(noncanonical, JSON.stringify(entry)).toBe(true);
    if (["product", "prop", "scene"].includes(entry.role)) {
      const perceptible = entry.maxTranslationFinalPx >= 0.125
        || entry.maxRotationDelta >= 0.25
        || entry.maxScaleXDelta >= 0.01
        || entry.maxScaleYDelta >= 0.01
        || entry.maxOpacityDelta >= 0.08;
      expect(perceptible, JSON.stringify(entry)).toBe(true);
    }
    expect(entry.maxTranslationFinalPx, JSON.stringify(entry)).toBeLessThanOrEqual(1.5);
    expect(entry.maxRotationDelta, JSON.stringify(entry)).toBeLessThanOrEqual(6);
  }
  const bgmEntry = entries.find(({ role }) => role === "bgm");
  expect(bgmEntry?.maxScaleXDelta, JSON.stringify(bgmEntry)).toBeLessThan(0.0001);
  expect(bgmEntry?.maxScaleYDelta, JSON.stringify(bgmEntry)).toBeLessThan(0.0001);
  expect(bgmEntry?.maxOpacityDelta, JSON.stringify(bgmEntry)).toBeGreaterThan(0.9);

  const loopStarts: LoopStartObservation[] = [];
  const continuity: ContinuityProbeResult[] = [];
  for (const role of roleNames) {
    try {
      const loopStart = await page.evaluate((roleName) => (
        (window as unknown as { agentRoleEntryProbe: EntryProbe })
          .agentRoleEntryProbe.observeLoopStart(roleName)
      ), role);
      loopStarts.push(loopStart);
      expect(loopStart.entryAnimationCount, JSON.stringify(loopStart)).toBeGreaterThan(0);
      expect(loopStart.loopCount, JSON.stringify(loopStart)).toBeGreaterThan(0);
      // Captured in a microtask queued by native animate(), before another frame.
      expect(loopStart.maxInitialPhaseDeltaMs, JSON.stringify(loopStart)).toBeLessThanOrEqual(2);
      continuity.push(await page.evaluate((roleName) => (
        (window as unknown as { agentRoleEntryProbe: EntryProbe })
          .agentRoleEntryProbe.compareEntryAndLoopPose(roleName)
      ), role));
    } catch (error) {
      throw new Error(`Native continuity probe failed for ${role}`, { cause: error });
    }
  }
  for (const result of continuity) {
    expect(result.maxMatrixDelta, JSON.stringify(result)).toBeLessThan(0.001);
    expect(result.maxOpacityDelta, JSON.stringify(result)).toBeLessThan(0.001);
    expect(result.maxScaleXDelta, JSON.stringify(result)).toBeLessThan(0.001);
    expect(result.maxScaleYDelta, JSON.stringify(result)).toBeLessThan(0.001);
  }

  console.log(JSON.stringify({ entries, loopStarts, continuity }, null, 2));
});
