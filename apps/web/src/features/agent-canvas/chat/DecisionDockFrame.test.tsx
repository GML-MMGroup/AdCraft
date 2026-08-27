import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DecisionDockDisclosure, DecisionDockFrame } from "./DecisionDockFrame.tsx";

afterEach(cleanup);

describe("DecisionDockFrame", () => {
  it("renders user-facing content and one primary action", () => {
    const submit = vi.fn();
    render(
      <DecisionDockFrame
        title="Choose a direction"
        context="Pick the visual approach."
        pending={false}
        issue={null}
        footerSummary="Selected: Warm"
        submitLabel="Submit selection"
        submitDisabled={false}
        onSubmit={submit}
      >
        <p>Choice content</p>
      </DecisionDockFrame>,
    );

    expect(screen.getByRole("article", { name: "Choose a direction" })).toBeTruthy();
    expect(screen.getByText("Choice content")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Submit selection" }));
    expect(submit).toHaveBeenCalledOnce();
  });

  it("locks its footer and announces busy state while submitting", () => {
    const submit = vi.fn();
    const { rerender } = render(
      <DecisionDockFrame
        title="Review media"
        context="Choose the next action."
        pending={false}
        issue={null}
        footerSummary="Accept this result"
        submitLabel="Accept"
        submitDisabled={false}
        onSubmit={submit}
      >
        <p>Media content</p>
      </DecisionDockFrame>,
    );

    screen.getByRole("button", { name: "Accept" }).focus();
    rerender(
      <DecisionDockFrame
        title="Review media"
        context="Choose the next action."
        pending
        issue={null}
        footerSummary="Accept this result"
        submitLabel="Accept"
        submitDisabled={false}
        onSubmit={submit}
      >
        <p>Media content</p>
      </DecisionDockFrame>,
    );

    const pendingAction = screen.getByRole("button", { name: "Submitting" }) as HTMLButtonElement;
    expect(screen.getByRole("article").getAttribute("aria-busy")).toBe("true");
    expect(pendingAction.disabled).toBe(false);
    expect(pendingAction.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(pendingAction);
    fireEvent.click(pendingAction);
    expect(submit).not.toHaveBeenCalled();
  });

  it("keeps technical details closed behind human-readable error copy", () => {
    render(
      <DecisionDockFrame
        title="Choose"
        context="Pick one."
        pending={false}
        issue={{
          summary: "Review this response and try again.",
          detail: "invalid.path: expected array",
          fieldId: null,
          retryable: true,
        }}
        footerSummary="Selected: Warm"
        submitLabel="Submit selection"
        submitDisabled={false}
        onSubmit={vi.fn()}
      >
        <p>Body</p>
      </DecisionDockFrame>,
    );

    expect(screen.getByRole("alert").textContent).toContain("Review this response and try again.");
    const details = screen.getByText("Technical details").closest("details");
    expect(details?.open).toBe(false);
    fireEvent.click(screen.getByText("Technical details"));
    expect(details?.open).toBe(true);
    expect(screen.getByText("invalid.path: expected array")).toBeTruthy();
  });

  it("uses a controlled accessible disclosure", () => {
    const change = vi.fn();
    const { rerender } = render(
      <DecisionDockDisclosure
        id="references"
        label="References"
        count={3}
        expanded={false}
        disabled={false}
        onExpandedChange={change}
      >
        <p>Reference list</p>
      </DecisionDockDisclosure>,
    );

    const trigger = screen.getByRole("button", { name: "References · 3" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(change).toHaveBeenCalledWith(true);

    rerender(
      <DecisionDockDisclosure
        id="references"
        label="References"
        count={3}
        expanded
        disabled={false}
        onExpandedChange={change}
      >
        <p>Reference list</p>
      </DecisionDockDisclosure>,
    );
    expect(screen.getByText("Reference list")).toBeTruthy();
  });
});
