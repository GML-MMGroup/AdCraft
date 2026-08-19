import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_REGION_SETTINGS } from "../features/home-typography/fontCatalog";
import { HomeTypographyLabPage } from "./HomeTypographyLabPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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

  it("downloads the complete current typography configuration as JSON", async () => {
    let exportedBlob: Blob | undefined;
    const createObjectURL = vi.fn((blob: Blob) => {
      exportedBlob = blob;
      return "blob:typography-config";
    });
    const revokeObjectURL = vi.fn();
    let downloadedFileName = "";

    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click() {
      downloadedFileName = this.download;
    });

    render(<HomeTypographyLabPage />);
    fireEvent.change(screen.getByLabelText("Typography target"), {
      target: { value: "heroBody" },
    });
    chooseFont("DM Sans");
    fireEvent.change(screen.getByLabelText("Weight"), { target: { value: "700" } });
    fireEvent.click(screen.getByRole("button", { name: "Export configuration" }));

    expect(downloadedFileName).toMatch(/^adcraft-home-typography-\d{4}-\d{2}-\d{2}\.json$/);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:typography-config");
    expect(JSON.parse(await exportedBlob?.text() ?? "")).toEqual({
      ...DEFAULT_REGION_SETTINGS,
      heroBody: {
        ...DEFAULT_REGION_SETTINGS.heroBody,
        fontId: "dm-sans",
        fontWeight: 700,
      },
    });
  });

  it("shows a lightweight error when configuration export fails", () => {
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => {
        throw new Error("Browser download APIs are unavailable");
      }),
      revokeObjectURL: vi.fn(),
    });

    render(<HomeTypographyLabPage />);
    fireEvent.click(screen.getByRole("button", { name: "Export configuration" }));

    expect(screen.getByText("Configuration could not be exported.")).toBeTruthy();
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

  it("shows handwritten font groups only for the Hero accent", () => {
    render(<HomeTypographyLabPage />);

    fireEvent.click(screen.getByLabelText("Font family"));
    expect(screen.queryByRole("option", { name: "Dancing Script" })).toBeNull();

    fireEvent.pointerDown(screen.getByTestId("home-typography-preview"));
    fireEvent.change(screen.getByLabelText("Typography target"), {
      target: { value: "heroAccent" },
    });
    fireEvent.click(screen.getByLabelText("Font family"));

    expect(screen.getByRole("group", { name: "Handwritten: Signature & calligraphy" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Handwritten: Casual pen" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Handwritten: Marker & brush" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Handwritten: Playful display" })).toBeTruthy();

    fireEvent.click(screen.getByRole("option", { name: "Dancing Script" }));
    expect(screen.getByTestId<HTMLElement>("home-typography-preview").style.getPropertyValue("--lab-hero-accent-font"))
      .toBe('"Dancing Script", cursive');
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
    expect(screen.getByLabelText("Font family").textContent).toContain("Georgia");
  });
});
