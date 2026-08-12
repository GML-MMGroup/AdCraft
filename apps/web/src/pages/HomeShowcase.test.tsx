import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HomeShowcase } from "./HomeShowcase";

describe("HomeShowcase", () => {
  it("renders the Home composition without functional controls in static mode", () => {
    render(<HomeShowcase mode="static" />);

    expect(screen.getByRole("heading", { level: 1, name: "One Sentence Becomes an Ad film." })).toBeTruthy();
    expect(screen.getByTestId("home-hero-accent").textContent).toBe("Ad film.");
    expect(screen.getByTestId("home-hero-accent").querySelector("svg")).toBeNull();
    expect(screen.queryByRole("button", { name: /create your project/i })).toBeNull();
    expect(screen.queryByText("Preview Case")).toBeNull();
  });

  it("pauses the Discover orbit while a card is hovered or focused", () => {
    const openPreview = vi.fn();
    const view = render(
      <HomeShowcase
        mode="interactive"
        interactions={{
          createProject: vi.fn(),
          openWorkflow: vi.fn(),
          openPreview,
          closePreview: vi.fn(),
        }}
      />,
    );

    const orbit = within(view.container).getByLabelText("Discover inspiration gallery");
    const card = within(view.container).getByRole("button", { name: "Campaign Flow" });

    expect(orbit.dataset.paused).toBe("false");
    fireEvent.pointerEnter(card);
    expect(orbit.dataset.paused).toBe("true");
    expect(card.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(card);
    expect(openPreview).toHaveBeenCalledTimes(1);

    fireEvent.pointerLeave(card);
    expect(orbit.dataset.paused).toBe("false");
    expect(card.getAttribute("aria-pressed")).toBe("false");

    fireEvent.focus(card);
    expect(orbit.dataset.paused).toBe("true");
    fireEvent.blur(card);
    expect(orbit.dataset.paused).toBe("false");
  });
});
