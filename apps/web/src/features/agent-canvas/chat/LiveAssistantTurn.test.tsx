import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { PresentationStreamView } from "../runtime/useAgentCanvasPresentationStreams.ts";
import { LiveAssistantTurn } from "./LiveAssistantTurn.tsx";

function view(overrides: Partial<PresentationStreamView> = {}): PresentationStreamView {
  return {
    stream_id: "stream-1", status: "open", generation_id: "generation-1", reasoning_text: "Thinking",
    text: "", reasoning_started_at: 1_000, answer_started_at: null, terminal_at_ms: null,
    last_sequence_no: 1, stream_kind: "assistant", turn_id: null, node_id: null,
    authoritative_id: null, error_code: null, protocol_error: null, last_event_type: "delta", last_event: null,
    ...overrides,
  };
}

describe("LiveAssistantTurn", () => {
  afterEach(cleanup);

  it("keeps streaming text out of the live region while announcing thinking once", () => {
    render(<LiveAssistantTurn view={view()} />);
    const container = document.querySelector(".agent-chat__live-turn")!;
    expect(container.getAttribute("aria-busy")).toBe("true");
    expect(container.getAttribute("aria-live")).toBe("off");
    expect(container.getAttribute("role")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Thinking…");
  });

  it("announces the answer phase when writing starts", () => {
    render(<LiveAssistantTurn view={view({ answer_started_at: 2_000, text: "Hello" })} />);
    expect(screen.getByRole("status").textContent).toBe("Writing response");
  });
});
