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
});
