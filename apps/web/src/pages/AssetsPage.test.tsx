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

    await screen.findByRole("heading", { name: "Portrait Spark" });
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

    expect(await screen.findByRole("dialog", { name: "Portrait Spark" })).toBeTruthy();
    expect(container.querySelector(".v2-asset-detail-panel")).toBeNull();
    expect(screen.getByRole("img", { name: "Front view" }).getAttribute("src")).toBe("/media/portrait-front.webp");

    fireEvent.click(screen.getByRole("button", { name: "Next asset view" }));

    expect(screen.getByRole("img", { name: "Side view" }).getAttribute("src")).toBe("/media/portrait-side.webp");

    fireEvent.keyDown(document, { key: "Escape" });

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
    const { container } = render(<AssetEntityViewerFallback onClose={onClose} />);
    const closeButton = container.querySelector(".v2-asset-viewer .icon-btn") as HTMLButtonElement;

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
    const { container } = render(
      <AssetEntityViewer
        detail={videoDetail}
        loading={false}
        feedback={null}
        onClose={vi.fn()}
        onUpdate={async () => {}}
        onTrash={() => {}}
        onRestore={() => {}}
        splitTags={(value) => value.split(",")}
      />,
    );
    const closeButton = container.querySelector(".v2-asset-viewer .icon-btn") as HTMLButtonElement;
    const video = container.querySelector("video") as HTMLVideoElement;

    await new Promise<void>(requestAnimationFrame);
    closeButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });

    expect(document.activeElement).toBe(video);
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
