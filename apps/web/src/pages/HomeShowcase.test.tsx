import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
