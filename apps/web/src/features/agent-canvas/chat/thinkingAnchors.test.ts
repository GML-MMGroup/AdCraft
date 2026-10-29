import { describe, expect, it } from "vitest";
import { brandThinkingAnchor } from "./thinkingAnchors.ts";

function stream(overrides: Partial<Parameters<typeof brandThinkingAnchor>[0][number]> = {}) {
  return {
    status: "completed" as const,
    reasoning_text: "Brand reasoning",
    authoritative_id: "card-1",
    turn_id: null,
    reasoning_started_at: 1_000,
    answer_started_at: 2_000,
    terminal_at_ms: 3_000,
    generation_id: "brand-gen:workflow:1",
    ...overrides,
  };
}

describe("brandThinkingAnchor", () => {
  it("returns the newest completed brand stream for a matching authoritative identity", () => {
    const older = stream({ terminal_at_ms: 3_000 });
    const newer = stream({ terminal_at_ms: 5_000, reasoning_text: "Newest reasoning" });
    expect(brandThinkingAnchor([older, newer], ["card-1"])?.reasoning_text).toBe("Newest reasoning");
  });

  it("ignores non-brand, incomplete, empty, and unrelated streams", () => {
    expect(brandThinkingAnchor([
      stream({ generation_id: "generation:1" }),
      stream({ status: "open" }),
      stream({ reasoning_text: "" }),
      stream({ authoritative_id: "card-2" }),
    ], ["card-1"])).toBeNull();
  });
});
