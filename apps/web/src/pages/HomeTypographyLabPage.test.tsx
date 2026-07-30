import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HomeTypographyLabPage } from "./HomeTypographyLabPage";

afterEach(cleanup);

describe("HomeTypographyLabPage", () => {
  function chooseFont(fontName: string) {
    if (!screen.queryByRole("listbox")) {
      fireEvent.click(screen.getByLabelText("Font family"));
    }
    fireEvent.click(screen.getByRole("option", { name: fontName }));
  }

  it("renders the typography lab in its dedicated dark theme", () => {
    render(<HomeTypographyLabPage />);

    expect(screen.getByRole("main").classList.contains("home-typography-lab--dark")).toBe(true);
  });

  it("applies an accent font independently from the Hero main title", () => {
    render(<HomeTypographyLabPage />);

    fireEvent.change(screen.getByLabelText("Typography target"), {
      target: { value: "heroAccent" },
    });
    chooseFont("DM Serif Display");

    const preview = screen.getByTestId<HTMLElement>("home-typography-preview");
    expect(preview.style.getPropertyValue("--lab-hero-accent-font"))
      .toBe('"DM Serif Display", serif');
    expect(preview.style.getPropertyValue("--lab-hero-main-font"))
      .not.toBe('"DM Serif Display", serif');
  });

  it("shows a selected background for the active font in the font menu", () => {
    render(<HomeTypographyLabPage />);

    fireEvent.click(screen.getByLabelText("Font family"));

    const selectedFont = screen.getByRole("option", { name: "Instrument Serif" });
    const otherFont = screen.getByRole("option", { name: "Manrope" });
    expect(selectedFont.getAttribute("aria-selected")).toBe("true");
    expect(selectedFont.classList.contains("is-selected")).toBe(true);
    expect(otherFont.getAttribute("aria-selected")).toBe("false");
    expect(otherFont.classList.contains("is-selected")).toBe(false);

    fireEvent.click(screen.getByRole("option", { name: "DM Sans" }));

    expect(screen.getByRole("listbox")).toBeTruthy();
    expect(screen.getByRole("option", { name: "DM Sans" }).classList.contains("is-selected")).toBe(true);
    expect(screen.getByRole("option", { name: "Instrument Serif" }).classList.contains("is-selected")).toBe(false);

    fireEvent.pointerDown(screen.getByTestId("home-typography-preview"));

    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("restores the selected region and all regions to production defaults", () => {
    render(<HomeTypographyLabPage />);

    fireEvent.change(screen.getByLabelText("Typography target"), {
      target: { value: "heroAccent" },
    });
    chooseFont("DM Serif Display");
    const resetSelectedButton = screen.getByRole("button", { name: "Reset selected region" });
    fireEvent.pointerDown(resetSelectedButton);
    fireEvent.click(resetSelectedButton);
    fireEvent.click(screen.getByRole("button", { name: "Reset all typography" }));

    expect(screen.getByText("Current recipe")).toBeTruthy();
    expect(screen.getByLabelText("Font family").textContent).toContain("Instrument Serif");
  });
});
