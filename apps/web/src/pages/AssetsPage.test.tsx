import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { AssetEntityViewerFallback, AssetsPage } from "./AssetsPage.tsx";
import AssetEntityViewer from "../features/assets/AssetEntityViewer.tsx";
import { v2AssetMediaUrl } from "../features/assets/v2AssetLibraryModel.ts";

const assetStyles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

const assetFixture = vi.hoisted(() => {
  const summary = {
    entity_id: "recommended-v1-character-001",
    scope: "my",
    entity_type: "character",
    library_category: "characters",
    display_name: "Portrait Spark",
    description: "Portrait reference",
    tags: ["portrait"],
    is_favorite: false,
    status: "active",
    preview_member: null,
    preview_url: "/media/portrait-spark.webp",
    member_count: 1,
  };
  const detail = {
    ...summary,
    scope: "recommended",
    members: [
      {
        member_id: "portrait-front",
        semantic_type: "character_front",
        asset_id: "portrait-front-asset",
        version_id: "portrait-front-version",
        public_url: "/media/portrait-front.webp",
        thumbnail_url: "/media/portrait-front-thumb.webp",
        media_type: "image",
        display_name: "Front view",
        is_primary: true,
      },
      {
        member_id: "portrait-side",
        semantic_type: "character_side",
        asset_id: "portrait-side-asset",
        version_id: "portrait-side-version",
        public_url: "/media/portrait-side.webp",
        thumbnail_url: "/media/portrait-side-thumb.webp",
        media_type: "image",
        display_name: "Side view",
      },
    ],
    catalog_source_url: "https://example.com/catalog",
    license_id: "CC0-1.0",
    attribution: "Example catalog",
  };

  return {
    detail,
    fetchDetail: vi.fn(),
    loadMore: vi.fn(),
    refresh: vi.fn(),
    summary,
  };
});

vi.mock("../features/assets/useRecommendedCatalog.ts", () => ({
  useRecommendedCatalog: () => ({
    status: {
      catalog_key: "adcraft-recommended-assets-v1",
      status: "ready",
      entity_count: 1,
      member_count: 1,
      expected_relative_path: "data/assets/catalogs/recommended/",
      message: "Recommended assets are ready.",
    },
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock("../features/assets/useV2AssetLibrary.ts", () => ({
  useV2AssetLibrary: ({ category }: { category: string }) => ({
    entities: [assetFixture.summary],
    nextCursor: null,
    loading: category === "scenes",
    loadingMore: false,
    error: null,
    refresh: assetFixture.refresh,
    loadMore: assetFixture.loadMore,
    fetchDetail: assetFixture.fetchDetail,
  }),
}));

describe("AssetsPage", () => {
  beforeEach(() => {
    assetFixture.fetchDetail.mockResolvedValue(assetFixture.detail);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders a Discover-style card using only the display name", () => {
    const { container } = render(<AssetsPage />);
    const card = screen.getByRole("button", { name: "Open asset Portrait Spark" });

    expect(card.textContent).toBe("Portrait Spark");
    expect(card.querySelector(".play-dot")).toBeNull();
    expect(card.textContent).not.toContain("recommended-v1-character-001");
    expect(container.querySelector(".v2-asset-entity-card-title")).toBeTruthy();
  });

  it("keeps the grid layout unchanged when a card opens the viewer", async () => {
    const { container } = render(<AssetsPage />);
    const layout = container.querySelector(".v2-asset-library-layout");

    expect(screen.queryByText("Select an asset to view its members.")).toBeNull();
    expect(layout?.classList.contains("is-detail-open")).toBe(false);

    fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);

    expect(await screen.findByRole("dialog", { name: "Portrait Spark" })).toBeTruthy();
    expect(layout?.classList.contains("is-detail-open")).toBe(false);
  });

  it("does not offer saving for a recommended detail", async () => {
    const { container } = render(<AssetsPage />);

    fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);

    await screen.findByRole("dialog", { name: "Portrait Spark" });
    expect(screen.queryByRole("button", { name: "Save to My Assets" })).toBeNull();
  });

  it("removes stale cards while a new category is loading", () => {
    const { container } = render(<AssetsPage />);

    expect(container.querySelectorAll(".v2-asset-entity-card")).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: "Scenes" }));

    expect(screen.getByText("Loading assets...")).toBeTruthy();
    expect(container.querySelectorAll(".v2-asset-entity-card")).toHaveLength(0);
    expect(container.querySelector(".v2-asset-detail-panel")).toBeNull();
  });

  it("contains full-bleed media inside the asset card", () => {
    const rule = assetStyles.match(/\.v2-asset-entity-card\.v2-asset-discover-card\s*\{([^}]*)\}/);
    const declarations = document.createElement("div").style;

    expect(rule).not.toBeNull();
    declarations.cssText = rule?.[1] ?? "";
    expect(declarations.position).toBe("relative");
    expect(declarations.overflow).toBe("hidden");
  });

  it("uses five fluid columns and intrinsic discover card media on desktop", () => {
    const gridRule = assetStyles.match(/\.v2-asset-library-grid\s*\{([^}]*)\}/);
    const cardRule = assetStyles.match(/\.v2-asset-entity-card\.v2-asset-discover-card\s*\{([^}]*)\}/);
    const mediaRule = assetStyles.match(/\.v2-asset-discover-card \.v2-asset-media\s*\{([^}]*)\}/);
    const gridDeclarations = document.createElement("div").style;
    const cardDeclarations = document.createElement("div").style;
    const mediaDeclarations = document.createElement("div").style;

    expect(gridRule).not.toBeNull();
    expect(cardRule).not.toBeNull();
    expect(mediaRule).not.toBeNull();

    gridDeclarations.cssText = gridRule?.[1] ?? "";
    cardDeclarations.cssText = cardRule?.[1] ?? "";
    mediaDeclarations.cssText = mediaRule?.[1] ?? "";

    expect(gridDeclarations.gridTemplateColumns).toBe("repeat(5, minmax(0, 1fr))");
    expect(cardDeclarations.aspectRatio).toBe("");
    expect(cardDeclarations.padding).toBe("0px");
    expect(mediaDeclarations.position).toBe("relative");
    expect(mediaDeclarations.height).toBe("auto");
    expect(mediaDeclarations.objectFit).toBe("contain");
  });

  it("uses non-overlapping five-to-one column ranges at the exact breakpoints", () => {
    const breakpointRules = [
      [1279, "repeat(4, minmax(0, 1fr))"],
      [959, "repeat(3, minmax(0, 1fr))"],
      [719, "repeat(2, minmax(0, 1fr))"],
      [479, "minmax(0, 1fr)"],
    ] as const;

    for (const [maxWidth, columns] of breakpointRules) {
      const rule = assetStyles.match(
        new RegExp(`@media \\(max-width: ${maxWidth}px\\) \\{\\s*\\.v2-asset-library-grid \\{([^}]*)\\}`),
      );
      const declarations = document.createElement("div").style;

      expect(rule).not.toBeNull();
      declarations.cssText = rule?.[1] ?? "";
      expect(declarations.gridTemplateColumns).toBe(columns);
    }
  });

  it("keeps empty discover media in normal flow with a 4/3 fallback footprint", () => {
    const rule = assetStyles.match(/\.v2-asset-discover-card \.v2-asset-media\.is-empty\s*\{([^}]*)\}/);
    const declarations = document.createElement("div").style;

    expect(rule).not.toBeNull();
    declarations.cssText = rule?.[1] ?? "";
    expect(declarations.position).toBe("relative");
    expect(declarations.aspectRatio).toBe("4 / 3");
  });

  it("contains asset card media without cropping it", () => {
    const rule = assetStyles.match(/\.v2-asset-discover-card \.v2-asset-media\s*\{([^}]*)\}/);
    const declarations = document.createElement("div").style;

    expect(rule).not.toBeNull();
    declarations.cssText = rule?.[1] ?? "";
    expect(declarations.objectFit).toBe("contain");
  });

  it("opens the selected asset in a dismissible modal viewer", async () => {
    const { container } = render(<AssetsPage />);
    const card = screen.getByRole("button", { name: "Open asset Portrait Spark" });

    fireEvent.click(card);

    const dialog = await screen.findByRole("dialog", { name: "Portrait Spark" });
    const backdrop = dialog.closest(".v2-asset-viewer-backdrop");
    expect(backdrop?.parentElement).toBe(document.body);
    expect(screen.getAllByRole("button", { name: "Close asset viewer" })).toHaveLength(1);
    expect(dialog.querySelector(".v2-asset-viewer-heading")).toBeNull();
    expect(dialog.querySelector(".v2-asset-viewer-thumbnails")).toBeNull();
    expect(dialog.querySelector(".v2-asset-viewer-details")).toBeNull();
    expect(dialog.querySelector("form")).toBeNull();
    expect(container.querySelector(".v2-asset-detail-panel")).toBeNull();
    expect(screen.getByRole("img", { name: "Front view" }).getAttribute("src")).toBe("/media/portrait-front.webp");
    expect(screen.getByText("Front view, view 1 of 2")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Next asset view" }));

    expect(screen.getByRole("img", { name: "Side view" }).getAttribute("src")).toBe("/media/portrait-side.webp");
    expect(screen.getByText("Side view, view 2 of 2")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Portrait Spark" })).toBeNull();
    expect(document.activeElement).toBe(card);
  });

  it("closes from the backdrop control and restores card focus", async () => {
    const { container } = render(<AssetsPage />);
    const card = screen.getByRole("button", { name: "Open asset Portrait Spark" });

    fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);
    expect(await screen.findByRole("dialog", { name: "Portrait Spark" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss asset viewer" }));

    expect(screen.queryByRole("dialog", { name: "Portrait Spark" })).toBeNull();
    expect(document.activeElement).toBe(card);
  });

  it("restores focus when the asset detail request fails", async () => {
    assetFixture.fetchDetail.mockRejectedValueOnce(new Error("Asset detail request failed."));
    render(<AssetsPage />);
    const card = screen.getByRole("button", { name: "Open asset Portrait Spark" });

    fireEvent.click(card);

    expect(await screen.findByText("Asset detail request failed.")).toBeTruthy();
    expect(document.activeElement).toBe(card);
  });

  it("keeps the lazy viewer fallback dismissible with the keyboard", () => {
    const onClose = vi.fn();
    render(<AssetEntityViewerFallback onClose={onClose} />);
    const closeButton = screen.getByRole("button", { name: "Close asset viewer" });

    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(closeButton);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("includes video controls in the viewer keyboard focus loop", async () => {
    const videoDetail = {
      ...assetFixture.detail,
      members: [{ ...assetFixture.detail.members[0], media_type: "video", public_url: "/media/portrait-video.mp4" }],
    };
    render(
      <AssetEntityViewer
        detail={videoDetail}
        loading={false}
        onClose={vi.fn()}
      />,
    );
    const closeButton = screen.getByRole("button", { name: "Close asset viewer" });
    const video = document.querySelector("video") as HTMLVideoElement;

    await new Promise<void>(requestAnimationFrame);
    closeButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });

    expect(document.activeElement).toBe(video);
  });

  it("centers a media-only lightbox against the viewport without cropping", () => {
    const backdropRule = assetStyles.match(/\.v2-asset-viewer-backdrop\s*\{([^}]*)\}/);
    const viewerRule = assetStyles.match(/\.v2-asset-viewer\s*\{([^}]*)\}/);
    const stageRule = assetStyles.match(/\.v2-asset-viewer-stage\s*\{([^}]*)\}/);
    const mediaRule = assetStyles.match(/\.v2-asset-viewer-stage \.v2-asset-media,\s*\.v2-asset-viewer-stage \.v2-asset-audio\s*\{([^}]*)\}/);
    const backdropDeclarations = document.createElement("div").style;
    const viewerDeclarations = document.createElement("div").style;
    const stageDeclarations = document.createElement("div").style;
    const mediaDeclarations = document.createElement("div").style;

    expect(backdropRule).not.toBeNull();
    expect(viewerRule).not.toBeNull();
    expect(stageRule).not.toBeNull();
    expect(mediaRule).not.toBeNull();

    backdropDeclarations.cssText = backdropRule?.[1] ?? "";
    viewerDeclarations.cssText = viewerRule?.[1] ?? "";
    stageDeclarations.cssText = stageRule?.[1] ?? "";
    mediaDeclarations.cssText = mediaRule?.[1] ?? "";

    expect(backdropDeclarations.position).toBe("fixed");
    expect(backdropDeclarations.inset).toBe("0px");
    expect(viewerDeclarations.width).toBe("calc(100vw - 64px)");
    expect(viewerDeclarations.maxWidth).toBe("1400px");
    expect(viewerRule?.[1]).toContain("height: calc(100dvh - 64px)");
    expect(viewerDeclarations.overflow).toBe("visible");
    expect(stageDeclarations.placeItems).toBe("center");
    expect(mediaDeclarations.width).toBe("auto");
    expect(mediaDeclarations.height).toBe("auto");
    expect(mediaDeclarations.maxHeight).toBe("100%");
    expect(mediaDeclarations.objectFit).toBe("contain");
  });

  it("does not use a thumbnail as full-viewer media", () => {
    expect(v2AssetMediaUrl({ ...assetFixture.detail.members[0], public_url: null })).toBeNull();
  });

  it("keeps long display names inside the title overlay", () => {
    const rule = assetStyles.match(/\.v2-asset-entity-card-title\s*\{([^}]*)\}/);
    const declarations = document.createElement("div").style;

    expect(rule).not.toBeNull();
    declarations.cssText = rule?.[1] ?? "";
    expect(declarations.whiteSpace).toBe("normal");
    expect(declarations.overflowWrap).toBe("anywhere");
    expect(declarations.getPropertyValue("-webkit-line-clamp")).toBe("2");
  });
});
