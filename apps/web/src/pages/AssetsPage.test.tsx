import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssetsPage } from "./AssetsPage.tsx";

const canonicalApi = vi.hoisted(() => ({
  listAgentCanvasMyAssets: vi.fn(),
  listAgentCanvasRecommendedAssets: vi.fn(),
}));

vi.mock("../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: canonicalApi,
}));

function imageLibraryItem(scope: "my" | "recommended", category: string) {
  return {
    entity_id: `${scope}-${category}-entity`,
    scope,
    entity_type: category === "characters" ? "character" : category === "scenes" ? "scene" : "prop",
    library_category: category,
    display_name: `${scope} ${category}`,
    tags: [category],
    status: "active",
    preview_url: `/api/v2/assets/${scope}-${category}-thumbnail/content`,
    preview_member: {
      asset_id: `${scope}-${category}-asset`,
      version_id: `${scope}-${category}-version`,
      public_url: `/api/v2/assets/${scope}-${category}-asset/content`,
    },
  };
}

function imageLibraryItems(scope: "my" | "recommended", category: string, count: number) {
  return Array.from({ length: count }, (_, index) => ({
    ...imageLibraryItem(scope, category),
    entity_id: `${scope}-${category}-entity-${index + 1}`,
    display_name: `${scope} ${category} ${index + 1}`,
    preview_member: {
      asset_id: `${scope}-${category}-asset-${index + 1}`,
      version_id: `${scope}-${category}-version-${index + 1}`,
      public_url: `/api/v2/assets/${scope}-${category}-asset-${index + 1}/content`,
    },
  }));
}

describe("AssetsPage", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    canonicalApi.listAgentCanvasMyAssets.mockReset();
    canonicalApi.listAgentCanvasRecommendedAssets.mockReset();
    canonicalApi.listAgentCanvasMyAssets.mockResolvedValue({
      items: [imageLibraryItem("my", "characters")],
    });
    canonicalApi.listAgentCanvasRecommendedAssets.mockResolvedValue({
      items: [imageLibraryItem("recommended", "characters")],
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads My Assets by category through the canonical Agent Canvas API", async () => {
    render(<AssetsPage />);

    await waitFor(() => {
      expect(canonicalApi.listAgentCanvasMyAssets).toHaveBeenCalledWith("characters");
    });
    expect(canonicalApi.listAgentCanvasRecommendedAssets).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: "Scenes" }));
    await waitFor(() => {
      expect(canonicalApi.listAgentCanvasMyAssets).toHaveBeenLastCalledWith("scenes");
    });
  });

  it("loads Recommended Assets through the canonical API without catalog polling", async () => {
    render(<AssetsPage />);

    fireEvent.click(screen.getByRole("tab", { name: "Recommended Assets" }));
    await waitFor(() => {
      expect(canonicalApi.listAgentCanvasRecommendedAssets).toHaveBeenCalledWith("characters");
    });
    expect(canonicalApi.listAgentCanvasMyAssets).toHaveBeenCalledTimes(1);
  });

  it("keeps Recommended Assets viewable while using their canonical content URL for the original preview", async () => {
    render(<AssetsPage />);

    fireEvent.click(screen.getByRole("tab", { name: "Recommended Assets" }));
    const card = await screen.findByRole("button", { name: "Open asset recommended characters" });
    fireEvent.click(card);

    const dialog = await screen.findByRole("dialog", { name: "recommended characters" });
    expect(dialog.querySelector("img")?.getAttribute("src")).toBe("/api/v2/assets/recommended-characters-asset/content");
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Trash" })).toBeNull();
  });

  it("filters canonical list results client-side", async () => {
    render(<AssetsPage />);

    await screen.findByRole("button", { name: "Open asset my characters" });
    fireEvent.change(screen.getByRole("textbox", { name: "Search assets" }), { target: { value: "not present" } });

    expect(screen.getByText("No assets found.")).toBeTruthy();
    expect(canonicalApi.listAgentCanvasMyAssets).toHaveBeenCalledTimes(1);
  });

  it("uses a lead contact sheet cluster before the patterned browse flow", async () => {
    canonicalApi.listAgentCanvasMyAssets.mockResolvedValue({
      items: imageLibraryItems("my", "characters", 10),
    });

    const { container } = render(<AssetsPage />);

    await screen.findByRole("button", { name: "Open asset my characters 1" });
    expect(container.querySelectorAll('[data-gallery-placement="feature"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-gallery-placement="support"]')).toHaveLength(4);
    expect(container.querySelectorAll('[data-gallery-placement="flow"]')).toHaveLength(5);
    expect(container.querySelector('[data-gallery-size="feature"]')).toBeTruthy();
    expect(container.querySelector('[data-gallery-size="wide"]')).toBeTruthy();
  });

  it("uses a hologram scene gallery for Recommended Assets scenes and keeps original scene previews available", async () => {
    canonicalApi.listAgentCanvasRecommendedAssets.mockResolvedValue({
      items: imageLibraryItems("recommended", "scenes", 5).map((item, index) => ({
        ...item,
        entity_id: `recommended-v1-scene-${String(index + 1).padStart(3, "0")}`,
        tags: ["scenes", index % 2 === 0 ? "night" : "interior"],
      })),
    });

    const { container } = render(<AssetsPage />);

    fireEvent.click(screen.getByRole("tab", { name: "Recommended Assets" }));
    fireEvent.click(screen.getByRole("tab", { name: "Scenes" }));

    const firstScene = await screen.findByRole("tab", { name: "Show hologram scene recommended scenes 1" });
    expect(container.querySelector('[data-testid="recommended-scenes-hologram"]')).toBeTruthy();
    expect(container.querySelectorAll("[data-hologram-scene-option]")).toHaveLength(5);
    expect(container.querySelector(".asset-contact-sheet")).toBeNull();
    expect(screen.getByText("recommended scenes 1", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();
    expect(container.querySelectorAll("canvas")).toHaveLength(2);
    expect(container.querySelectorAll(".recommended-scenes-hologram__scene")).toHaveLength(1);
    await waitFor(() => expect(firstScene.getAttribute("aria-pressed")).toBe("true"));

    fireEvent.click(screen.getByRole("tab", { name: "Show hologram scene recommended scenes 2" }));
    await waitFor(() => {
      expect(screen.getByText("recommended scenes 2", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();
    });
    expect(container.querySelector<HTMLImageElement>(".recommended-scenes-hologram__scene")?.src).toContain(
      "/assets/hologram/scene-002-multi-view.png",
    );

    fireEvent.click(screen.getByRole("button", { name: "Next hologram scene" }));
    await waitFor(() => {
      expect(screen.getByText("recommended scenes 3", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Previous hologram scene" }));
    await waitFor(() => {
      expect(screen.getByText("recommended scenes 2", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Open original scene recommended scenes 2" }));
    const dialog = await screen.findByRole("dialog", { name: "recommended scenes 2" });
    expect(dialog.querySelector("img")?.getAttribute("src")).toBe("/api/v2/assets/recommended-scenes-asset-2/content");
  });

  it("maps each canonical recommended scene ID to its own transparent hologram asset", async () => {
    canonicalApi.listAgentCanvasRecommendedAssets.mockResolvedValue({
      items: [
        { ...imageLibraryItem("recommended", "scenes"), entity_id: "recommended-v1-scene-001", display_name: "First scene" },
        { ...imageLibraryItem("recommended", "scenes"), entity_id: "recommended-v1-scene-002", display_name: "Second scene" },
      ],
    });

    const { container } = render(<AssetsPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Recommended Assets" }));
    fireEvent.click(screen.getByRole("tab", { name: "Scenes" }));

    await screen.findByRole("tab", { name: "Show hologram scene First scene" });
    const projection = () => container.querySelector<HTMLImageElement>(".recommended-scenes-hologram__scene");
    expect(projection()?.getAttribute("src")).toBe("/assets/hologram/scene-001-multi-view.png");

    fireEvent.click(screen.getByRole("tab", { name: "Show hologram scene Second scene" }));
    await waitFor(() => {
      expect(projection()?.getAttribute("src")).toBe("/assets/hologram/scene-002-multi-view.png");
    });
  });

  it("keeps the hologram scene stage unclipped and makes its generated scene asset transparent", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/pages/assets.css"), "utf8");
    const sceneSource = readFileSync(resolve(process.cwd(), "src/features/assets/RecommendedSceneHologram.tsx"), "utf8");

    expect(styles).toMatch(/\.recommended-scenes-hologram\s*\{[^}]*overflow:\s*visible/s);
    expect(styles).toMatch(/\.recommended-scenes-hologram__scene\s*\{[^}]*object-fit:\s*contain/s);
    expect(sceneSource).toContain("hologramSceneUrlForAsset");
  });

  it("uses the documented 16:10 projection stack and static screen-blended beam", () => {
    const styles = readFileSync(resolve(process.cwd(), "src/pages/assets.css"), "utf8");

    expect(styles).toMatch(/\.recommended-scenes-hologram__projection-wrap\s*\{[^}]*aspect-ratio:\s*16\s*\/\s*10/s);
    expect(styles).toMatch(/\.recommended-scenes-hologram__beam\s*\{[^}]*mix-blend-mode:\s*screen[^}]*opacity:\s*0\.88[^}]*saturate\(1\.08\)/s);
    expect(styles).toMatch(/\.recommended-scenes-hologram__scene\s*\{[^}]*object-fit:\s*contain[^}]*opacity:\s*0\.9/s);
    expect(styles).toMatch(/\.recommended-scenes-hologram__glow\s*\{[^}]*radial-gradient[^}]*blur\(20px\)/s);
  });

  it("does not retain retired standalone asset-library route dependencies", () => {
    const source = readFileSync(resolve(process.cwd(), "src/pages/AssetsPage.tsx"), "utf8");

    expect(source).not.toContain("useV2AssetLibrary");
    expect(source).not.toContain("useRecommendedCatalog");
    expect(source).not.toContain("recommendedCatalogStatus");
    expect(source).not.toContain("/asset-library/");
    expect(source).not.toContain("catalogs/recommended/status");
  });
});
