import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  isLikelyMarkdown,
  renderMarkdownAwareText,
} from "./AgentCanvasMarkdown.tsx";

describe("AgentCanvasMarkdown", () => {
  it("leaves ordinary text on the plain-text rendering path", () => {
    expect(isLikelyMarkdown("A concise product direction for a premium watch.")).toBe(false);
  });

  it("detects and renders supported Markdown blocks and inline emphasis", () => {
    const source = "## Direction\n\n- **Warm** light\n- Motion in the final beat";

    render(<div>{renderMarkdownAwareText(source)}</div>);

    expect(isLikelyMarkdown(source)).toBe(true);
    expect(screen.getByRole("heading", { name: "Direction" })).toBeTruthy();
    expect(screen.getByRole("list")).toBeTruthy();
    expect(screen.getByText("Warm").tagName).toBe("STRONG");
  });

  it("blocks unsafe Markdown links", () => {
    render(<div>{renderMarkdownAwareText("[Do not open](javascript:alert(1))")}</div>);

    expect(screen.getByRole("link", { name: "Unsafe link blocked" }).getAttribute("href")).toBe("#");
  });
});
