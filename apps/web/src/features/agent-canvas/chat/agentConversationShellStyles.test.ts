import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Agent Conversation Shell responsive layout", () => {
  it("keeps the composer reachable on short viewports without clipping the shell", () => {
    const styles = readFileSync(resolve(
      process.cwd(),
      "src/features/agent-canvas/chat/agent-canvas-chat.css",
    ), "utf8");
    const start = styles.indexOf("@media (max-height: 720px)");
    const end = styles.indexOf("@media (prefers-reduced-motion: reduce)", start);
    const shortViewport = start >= 0 ? styles.slice(start, end) : "";

    const shell = styles.match(/\.agent-chat \{([\s\S]*?)\n\}/)?.[1] ?? "";

    expect(shell).toContain("display: flex");
    expect(shell).toContain("flex-direction: column");
    expect(shortViewport).toContain(".agent-chat__timeline-shell");
    expect(shortViewport).not.toMatch(/\.agent-chat\s*\{[^}]*overflow-y:\s*auto/);
  });
});
