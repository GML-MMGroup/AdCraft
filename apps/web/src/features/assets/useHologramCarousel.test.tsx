import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useHologramCarousel } from "./useHologramCarousel.ts";

const ITEMS = ["scene-1", "scene-2", "scene-3"];

function Harness({ reducedMotion = false }: { reducedMotion?: boolean }) {
  const carousel = useHologramCarousel(ITEMS, {
    autoAdvanceMs: 9_000,
    interactionResumeMs: 3_200,
    preload: vi.fn(),
    reducedMotion,
  });

  return (
    <div>
      <output data-testid="active-scene">{carousel.activeId}</output>
      <output data-testid="displayed-scene">{carousel.displayedId}</output>
      <button type="button" onClick={() => carousel.previous()}>Previous</button>
      <button type="button" onClick={() => carousel.next()}>Next</button>
      <button type="button" onClick={() => carousel.select("scene-3")}>Select third</button>
      <button type="button" onClick={() => carousel.setPaused("hover", true)}>Pause</button>
      <button type="button" onClick={() => carousel.setPaused("hover", false)}>Resume</button>
    </div>
  );
}

describe("useHologramCarousel", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("wraps previous and next navigation without an endpoint", () => {
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-3");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-1");
    fireEvent.click(screen.getByRole("button", { name: "Select third" }));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-3");
  });

  it("auto advances, pauses during interaction, and resumes after the delay", () => {
    vi.useFakeTimers();
    render(<Harness />);

    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    act(() => vi.advanceTimersByTime(18_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");

    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    act(() => vi.advanceTimersByTime(3_199));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");
    act(() => vi.advanceTimersByTime(1));
    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-3");
  });

  it("does not auto advance when reduced motion is enabled", () => {
    vi.useFakeTimers();
    render(<Harness reducedMotion />);

    act(() => vi.advanceTimersByTime(30_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-1");
  });

  it("fades the old scene before swapping the single displayed image", () => {
    vi.useFakeTimers();
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByTestId("displayed-scene").textContent).toBe("scene-1");
    act(() => vi.advanceTimersByTime(159));
    expect(screen.getByTestId("displayed-scene").textContent).toBe("scene-1");
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByTestId("displayed-scene").textContent).toBe("scene-2");
  });
});
