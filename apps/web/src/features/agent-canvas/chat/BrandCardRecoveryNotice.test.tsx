import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrandCardRecoveryNotice } from "./BrandCardRecoveryNotice";

afterEach(cleanup);
it("keeps refresh unavailable during a running turn and requires a click when it finishes", () => {
  const onRefresh = vi.fn();
  const state = { interactionId: "old", phase: "stale" as const, needsQuestion: true, error: null };
  const { rerender } = render(<BrandCardRecoveryNotice state={state} busy onRefresh={onRefresh}/>);
  fireEvent.click(screen.getByRole("button", { name: "Refresh question" }));
  expect(onRefresh).not.toHaveBeenCalled();
  rerender(<BrandCardRecoveryNotice state={state} busy={false} onRefresh={onRefresh}/>);
  expect(onRefresh).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh question" }));
  expect(onRefresh).toHaveBeenCalledOnce();
});

it("retains the reload action after read failure and renders error messages as text", () => {
  render(<BrandCardRecoveryNotice state={{ interactionId: "old", phase: "error", needsQuestion: false,
    error: "<img src=x onerror=alert(1)>" }} busy={false} onRefresh={() => {}}/>);
  expect(screen.getByRole("button", { name: "Reload current question" })).toBeTruthy();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  expect(document.querySelector("img")).toBeNull();
});
