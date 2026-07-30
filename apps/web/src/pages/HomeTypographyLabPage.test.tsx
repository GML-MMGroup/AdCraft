import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HomeTypographyLabPage } from "./HomeTypographyLabPage";

afterEach(cleanup);

describe("HomeTypographyLabPage", () => {
  it("applies an accent font independently from the Hero main title", () => {
    render(<HomeTypographyLabPage />);

    fireEvent.change(screen.getByLabelText("Typography target"), {
      target: { value: "heroAccent" },
    });
    fireEvent.change(screen.getByLabelText("Font family"), {
      target: { value: "dm-serif-display" },
    });

    const preview = screen.getByTestId<HTMLElement>("home-typography-preview");
    expect(preview.style.getPropertyValue("--lab-hero-accent-font"))
      .toBe('"DM Serif Display", serif');
    expect(preview.style.getPropertyValue("--lab-hero-main-font"))
      .not.toBe('"DM Serif Display", serif');
  });

  it("restores the selected region and all regions to production defaults", () => {
    render(<HomeTypographyLabPage />);

    fireEvent.change(screen.getByLabelText("Typography target"), {
      target: { value: "heroAccent" },
    });
    fireEvent.change(screen.getByLabelText("Font family"), {
      target: { value: "dm-serif-display" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset selected region" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset all typography" }));

    expect(screen.getByText("Current recipe")).toBeTruthy();
    expect(screen.getByDisplayValue("Instrument Serif")).toBeTruthy();
  });
});
