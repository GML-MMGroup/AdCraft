import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationRecoverySurface } from "./ConversationRecoverySurface.tsx";
import type { ConversationRecoveryView } from "./conversationRecovery.ts";

afterEach(cleanup);

const retryRecovery: ConversationRecoveryView = {
  scope: "composer",
  title: "Response could not be submitted",
  message: "Your message is still here. Try sending it again.",
  technicalDetail: "provider_unavailable: Request failed with status 500",
  action: "retry",
};

describe("ConversationRecoverySurface", () => {
  it("focuses and announces newly rendered recovery without exposing technical detail", () => {
    render(<ConversationRecoverySurface recovery={retryRecovery} onAction={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(document.activeElement).toBe(alert);
    expect(alert.textContent).toContain(retryRecovery.title);
    expect(alert.textContent).toContain(retryRecovery.message);
    expect(alert.textContent).not.toContain("provider_unavailable");
  });

  it("keeps technical details closed until explicitly expanded", () => {
    render(<ConversationRecoverySurface recovery={retryRecovery} onAction={vi.fn()} />);

    const disclosure = screen.getByText("Technical details").closest("details")!;
    expect(disclosure.open).toBe(false);
    fireEvent.click(screen.getByText("Technical details"));
    expect(disclosure.open).toBe(true);
    expect(screen.getByText("provider_unavailable: Request failed with status 500")).toBeTruthy();
  });

  it.each([
    ["retry", "Retry"],
    ["refresh", "Refresh"],
    ["review", "Review latest"],
  ] as const)("renders one %s action", (action, label) => {
    const onAction = vi.fn();
    render(
      <ConversationRecoverySurface
        recovery={{ ...retryRecovery, action }}
        onAction={onAction}
      />,
    );

    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(onAction).toHaveBeenCalledOnce();
  });

  it("renders no recovery action when none is allowed", () => {
    render(
      <ConversationRecoverySurface
        recovery={{ ...retryRecovery, action: "none" }}
        onAction={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button")).toBeNull();
  });
});
