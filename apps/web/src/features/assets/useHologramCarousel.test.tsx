import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useHologramCarousel } from "./useHologramCarousel.ts";

const ITEMS = ["scene-1", "scene-2", "scene-3"];

function Harness({ reducedMotion = false }: { reducedMotion?: boolean }) {
  const carousel = useHologramCarousel(ITEMS, {
    autoAdvanceMs: 9_000,
    preload: vi.fn(),
    reducedMotion,
  });

  return (
    <div>
      <output data-testid="active-scene">{carousel.activeId}</output>
      <output data-testid="outgoing-scene">{carousel.outgoingId}</output>
      <output data-testid="transition-direction">{carousel.transitionDirection}</output>
      <output data-testid="is-transitioning">{String(carousel.isTransitioning)}</output>
      <button type="button" onClick={() => carousel.previous()}>Previous</button>
      <button type="button" onClick={() => carousel.next()}>Next</button>
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
  });

  it("auto advances, pauses while hovered, and resumes immediately after hover", () => {
    vi.useFakeTimers();
    render(<Harness />);

    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    act(() => vi.advanceTimersByTime(18_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");

    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    act(() => vi.advanceTimersByTime(8_999));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-3");
  });

  it("keeps auto advancing without animation when reduced motion is enabled", () => {
    vi.useFakeTimers();
    render(<Harness reducedMotion />);

    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");
    expect(screen.getByTestId("outgoing-scene").textContent).toBe("");
    expect(screen.getByTestId("is-transitioning").textContent).toBe("false");
  });

  it("exposes paired outgoing and incoming scenes with directional transitions", () => {
    vi.useFakeTimers();
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByTestId("active-scene").textContent).toBe("scene-2");
    expect(screen.getByTestId("outgoing-scene").textContent).toBe("scene-1");
    expect(screen.getByTestId("transition-direction").textContent).toBe("forward");
    expect(screen.getByTestId("is-transitioning").textContent).toBe("true");

    act(() => vi.advanceTimersByTime(560));
    expect(screen.getByTestId("outgoing-scene").textContent).toBe("");
    expect(screen.getByTestId("is-transitioning").textContent).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByTestId("outgoing-scene").textContent).toBe("scene-2");
    expect(screen.getByTestId("transition-direction").textContent).toBe("backward");
  });
});
