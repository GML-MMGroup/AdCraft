import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./app/useHealth", () => ({
  useHealth: () => ({ startNewProject: vi.fn() }),
}));

beforeEach(() => {
  window.history.replaceState({}, "", "/design-lab/home-typography");
});

afterEach(cleanup);

describe("Home typography lab route", () => {
  it("renders the typography lab only at its explicit internal path", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Home Typography Lab" })).toBeTruthy();
    expect(screen.queryByLabelText("Primary navigation")).toBeNull();
  });
});
