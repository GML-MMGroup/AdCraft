import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ModeSelectionPage } from "./ModeSelectionPage";

const { create, navigate } = vi.hoisted(() => ({ create: vi.fn(), navigate: vi.fn() }));
vi.mock("../AppContextValue", () => ({ useApp: () => ({ startNewProject: create }) }));
vi.mock("../features/mode-selection/ModeLaunchContext", () => ({ useModeLaunch: () => ({ begin: navigate, revealing: false, preparing: false, keyboard: false }) }));
vi.mock("../features/mode-icon-lab/ParticleIconStudy", () => ({ ParticleIconStudy: () => null }));

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it.each([["Personal Creation", "creation"], ["Brand Professional", "brand"]])(
  "creates %s immediately, blocks duplicate clicks and hands off to the persistent layer",
  async (label, mode) => {
    create.mockResolvedValue("project-123");
    render(<ModeSelectionPage />);
    const button = screen.getByRole("button", { name: new RegExp(label) });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(create).toHaveBeenCalledExactlyOnceWith(mode);
    expect(navigate).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(navigate).toHaveBeenCalledWith(mode, "project-123", true);
    expect(document.querySelector(".is-selecting")).toBeNull();
  },
);

it("restores selection after failure and allows retry", async () => {
  create.mockResolvedValueOnce(null).mockResolvedValueOnce("retry");
  render(<ModeSelectionPage />);
  fireEvent.click(screen.getByRole("button", { name: /Brand Professional/ }));
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(screen.getByRole("alert").textContent).toContain("try again");
  expect(navigate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Personal Creation/ }));
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(create).toHaveBeenLastCalledWith("creation");
  expect(navigate).toHaveBeenCalledWith("creation", "retry", true);
});

it("does not navigate away after the chooser unmounts", async () => {
  create.mockResolvedValue("late");
  const view = render(<ModeSelectionPage />);
  fireEvent.click(screen.getByRole("button", { name: /Brand Professional/ }));
  view.unmount();
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(navigate).not.toHaveBeenCalled();
});
