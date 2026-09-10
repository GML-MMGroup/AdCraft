import { expect, test } from "@playwright/test";

interface PreparedReveal {
  clipId: string;
  part: string;
  role: "product" | "prop";
  sampleTimeMs: number;
  targetMatrixDelta: number;
  windowMatrixDelta: number;
}

interface PixelEvidence {
  outsideClipPixels: number;
  paintedBounds: { bottom: number; left: number; right: number; top: number };
  paintedPixels: number;
}

interface ClipProbe {
  analyzeRevealPng(base64Png: string): Promise<PixelEvidence>;
  caseNames: string[];
  prepareReveal(name: string): Promise<PreparedReveal>;
  restoreReveal(): void;
}

test("Product glass and Prop guide reveals move behind fixed native clip windows", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-clip-windows-mock.html");
  await page.waitForFunction(() => "agentRoleClipProbe" in window);
  const caseNames = await page.evaluate(() => (
    (window as unknown as { agentRoleClipProbe: ClipProbe })
      .agentRoleClipProbe.caseNames
  ));
  const evidence: Array<PreparedReveal & PixelEvidence> = [];

  for (const name of caseNames) {
    const prepared = await page.evaluate((caseName) => (
      (window as unknown as { agentRoleClipProbe: ClipProbe })
        .agentRoleClipProbe.prepareReveal(caseName)
    ), name);
    const screenshot = await page.locator(
      `[data-probe-role="${prepared.role}"]`,
    ).screenshot({ animations: "allow" });
    const pixels = await page.evaluate((base64Png) => (
      (window as unknown as { agentRoleClipProbe: ClipProbe })
        .agentRoleClipProbe.analyzeRevealPng(base64Png)
    ), screenshot.toString("base64"));
    evidence.push({ ...prepared, ...pixels });
    await page.evaluate(() => (
      (window as unknown as { agentRoleClipProbe: ClipProbe })
        .agentRoleClipProbe.restoreReveal()
    ));
  }

  for (const result of evidence) {
    expect.soft(result.targetMatrixDelta, JSON.stringify(result))
      .toBeGreaterThan(1);
    expect.soft(result.windowMatrixDelta, JSON.stringify(result))
      .toBeLessThan(0.001);
    expect.soft(result.paintedPixels, JSON.stringify(result))
      .toBeGreaterThan(20);
    expect.soft(result.outsideClipPixels, JSON.stringify(result))
      .toBeLessThanOrEqual(Math.max(4, result.paintedPixels * 0.01));
  }

  console.log(JSON.stringify({ clipWindowEvidence: evidence }, null, 2));
});
