import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("AgentCanvasPage chrome", () => {
  it("hides the React Flow attribution panel", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPage.tsx"),
      "utf8",
    );

    expect(source).toContain("proOptions={{ hideAttribution: true }}");
  });

  it("extends only the Workflow bottom inset without widening the canvas shell", () => {
    const baseCss = readFileSync(resolve(process.cwd(), "src/styles/base.css"), "utf8");
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(baseCss).toContain("min-height: calc(100dvh - 16px)");
    expect(baseCss).toContain("margin: 16px auto 0");
    expect(canvasCss).toContain("height: calc(100dvh - var(--topbar-height) - 16px)");
  });
});
