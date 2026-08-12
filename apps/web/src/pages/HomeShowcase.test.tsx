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

  it("centers an initial Discover card and supports keyboard navigation", () => {
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
    const card = within(view.container).getByRole("button", { name: "Scene Extension" });

    expect(orbit.getAttribute("aria-roledescription")).toBe("carousel");
    expect(orbit.dataset.activeIndex).toBe("3");
    expect(card.getAttribute("aria-current")).toBe("true");

    fireEvent.keyDown(card, { key: "ArrowRight" });
    expect(orbit.dataset.activeIndex).toBe("4");
    expect(card.getAttribute("aria-current")).toBe("false");

    fireEvent.keyDown(card, { key: "ArrowLeft" });
    expect(orbit.dataset.activeIndex).toBe("3");

    fireEvent.click(card);
    expect(openPreview).toHaveBeenCalledTimes(1);
  });
});
