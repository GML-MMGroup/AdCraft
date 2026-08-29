import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { RecommendedCharacterGrid } from "./RecommendedCharacterGrid.tsx";

function character(id: string, displayName: string): AgentAssetBrowserItem {
  return {
    id,
    assetId: `${id}-asset`,
    source: "recommended",
    mediaType: "image",
    displayName,
    previewUrl: `/images/${id}.png`,
    mediaUrl: `/images/${id}-full.png`,
    status: "ready",
    tags: ["character", "hero", "unused-tag"],
    identity: {
      source: "recommended",
      assetId: `${id}-asset`,
      entityId: `${id}-entity`,
      versionId: `${id}-version`,
    },
    projectAsset: null,
  };
}

const characters = [
  character("character-1", "Mina"),
  character("character-2", "Otto"),
  character("character-3", "Ravi"),
];

afterEach(cleanup);

describe("RecommendedCharacterGrid", () => {
  it("renders equal comparison cards with names and at most two real tags", () => {
    render(
      <RecommendedCharacterGrid
        assets={characters}
        selectedAssetId={null}
        loading={false}
        error={null}
        buttonRef={vi.fn()}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("region", { name: "Recommended characters" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Open asset/ })).toHaveLength(3);
    expect(screen.getAllByText("character", { selector: ".recommended-character-card__tag" })).toHaveLength(3);
    expect(screen.getAllByText("hero", { selector: ".recommended-character-card__tag" })).toHaveLength(3);
    expect(screen.queryByText("unused-tag", { selector: ".recommended-character-card__tag" })).toBeNull();
    expect(screen.queryByText("Featured assets")).toBeNull();
  });

  it("opens the selected asset through the existing callback", () => {
    const onSelect = vi.fn();
    render(
      <RecommendedCharacterGrid
        assets={characters}
        selectedAssetId="character-2"
        loading={false}
        error={null}
        buttonRef={vi.fn()}
        onSelect={onSelect}
      />,
    );

    const button = screen.getByRole("button", { name: "Open asset Otto" });
    fireEvent.click(button);

    expect(onSelect).toHaveBeenCalledWith(characters[1], button);
    expect(button.className).toContain("is-selected");
  });

  it("renders loading, error, and empty gallery states", () => {
    const { rerender } = render(
      <RecommendedCharacterGrid
        assets={[]}
        selectedAssetId={null}
        loading
        error={null}
        buttonRef={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole("status", { name: "Loading recommended characters" })).toBeTruthy();
    expect(screen.getAllByTestId("recommended-character-skeleton")).toHaveLength(4);

    rerender(
      <RecommendedCharacterGrid
        assets={[]}
        selectedAssetId={null}
        loading={false}
        error="Recommended character assets failed to load."
        buttonRef={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Recommended character assets failed to load.");

    rerender(
      <RecommendedCharacterGrid
        assets={[]}
        selectedAssetId={null}
        loading={false}
        error={null}
        buttonRef={vi.fn()}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("No recommended characters found.")).toBeTruthy();
  });

  it("defines the comparison-first three-view grid and responsive breakpoints", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/pages/assets.css"), "utf8");

    expect(styles).toMatch(/\.recommended-character-grid__cards[^}]*grid-template-columns:\s*repeat\(4/);
    expect(styles).toMatch(/\.recommended-character-card__media-frame[^}]*aspect-ratio:\s*2\s*\/\s*1/);
    expect(styles).toMatch(/\.recommended-character-card__media[^}]*object-fit:\s*contain/);
    expect(styles).toMatch(/@media \(max-width: 959px\)/);
    expect(styles).toMatch(/@media \(max-width: 719px\)/);
    expect(styles).toMatch(/@media \(max-width: 479px\)/);
  });
});
