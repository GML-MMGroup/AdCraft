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

  it("renders two linked Discover tracks and supports keyboard navigation", () => {
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
    const upperTrack = orbit.querySelector("[data-discover-track=upper]");
    const lowerTrack = orbit.querySelector("[data-discover-track=lower]");
    const card = within(upperTrack as HTMLElement).getByRole("button", { name: "upper Scene Extension" });

    expect(orbit.getAttribute("aria-roledescription")).toBe("carousel");
    expect(upperTrack).toBeTruthy();
    expect(lowerTrack).toBeTruthy();
    expect(orbit.dataset.activeIndex).toContain("upper:3");
    expect(orbit.dataset.activeIndex).toContain("lower:2");
    expect(card.getAttribute("aria-current")).toBe("true");
    expect(within(lowerTrack as HTMLElement).getByRole("button", { name: "lower Poster Motion" }).getAttribute("aria-current")).toBe("true");

    fireEvent.keyDown(card, { key: "ArrowRight" });
    expect(orbit.dataset.activeIndex).not.toContain("upper:3");
    expect(card.getAttribute("aria-current")).toBe("false");

    fireEvent.keyDown(card, { key: "ArrowLeft" });
    expect(orbit.dataset.activeIndex).toContain("upper:3");

    const lowerCard = within(lowerTrack as HTMLElement).getByRole("button", { name: "lower Product Aura" });
    fireEvent.click(lowerCard);
    expect(card.getAttribute("aria-current")).toBe("true");
    expect(lowerCard.getAttribute("aria-current")).toBe("true");
    expect(orbit.dataset.activeIndex).toContain("upper:3");
    expect(orbit.dataset.activeIndex).toContain("lower:4");

    fireEvent.click(card);
    expect(openPreview).toHaveBeenCalledTimes(1);
  });

});
