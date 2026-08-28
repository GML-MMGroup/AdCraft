import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProposalOptionRow } from "./ProposalOptionRow.tsx";

afterEach(cleanup);

describe("ProposalOptionRow", () => {
  it("renders a selectable option with its recommendation and selection state", () => {
    const onSelect = vi.fn();
    render(
      <ProposalOptionRow
        index={0}
        optionId="option-a"
        title="Warm world"
        summary="A soft, intimate direction."
        recommended
        selected
        onSelect={onSelect}
      />,
    );

    const option = screen.getByRole("button", { name: /Warm world/i });
    expect(option.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Recommended")).toBeTruthy();
    expect(screen.getByText("01")).toBeTruthy();

    fireEvent.click(option);
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("renders the same structure as a read-only historical option", () => {
    render(
      <ProposalOptionRow
        index={1}
        optionId="option-b"
        title="Clean precision"
        summary="A restrained product direction."
        selected
        readOnly
      />,
    );

    expect(screen.getByLabelText("Selected option: Clean precision")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Clean precision/i })).toBeNull();
    expect(screen.getByText("02")).toBeTruthy();
  });

  it("supports Decision Dock radio semantics and a letter marker", () => {
    render(
      <ProposalOptionRow
        index={1}
        marker="B"
        selectionRole="radio"
        optionId="option-b"
        title="Precise"
        summary="Clean product precision."
        selected
        onSelect={vi.fn()}
      />,
    );

    const option = screen.getByRole("radio", { name: /Precise/i });
    expect(option.getAttribute("aria-checked")).toBe("true");
    expect(option.getAttribute("aria-pressed")).toBeNull();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("✓")).toBeTruthy();
  });
});
