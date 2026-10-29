import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentThinkingBlock } from "./AgentThinkingBlock.tsx";

describe("AgentThinkingBlock", () => {
  afterEach(cleanup);

  it("uses the visible phase label as the toggle accessible name", () => {
    render(<AgentThinkingBlock reasoningText="Reasoning" phase="done" durationSeconds={4} />);
    const toggle = screen.getByRole("button", { name: "Thought for 4s" });
    expect(toggle.getAttribute("aria-label")).toBeNull();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });
});
