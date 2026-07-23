import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { AssetsPage } from "./AssetsPage.tsx";

const assetStyles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

const assetFixture = vi.hoisted(() => {
  const summary = {
    entity_id: "recommended-v1-character-001",
    scope: "recommended",
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
    members: [],
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
  useV2AssetLibrary: () => ({
    entities: [assetFixture.summary],
    nextCursor: null,
    loading: false,
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

  it("does not reserve a detail panel until a card is selected", async () => {
    const { container } = render(<AssetsPage />);
    const layout = container.querySelector(".v2-asset-library-layout");

    expect(screen.queryByText("Select an asset to view its members.")).toBeNull();
    expect(layout?.classList.contains("is-detail-open")).toBe(false);

    fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);

    expect(await screen.findByRole("heading", { name: "Portrait Spark" })).toBeTruthy();
    expect(layout?.classList.contains("is-detail-open")).toBe(true);
  });

  it("does not offer saving for a recommended detail", async () => {
    const { container } = render(<AssetsPage />);

    fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);

    await screen.findByRole("heading", { name: "Portrait Spark" });
    expect(screen.queryByRole("button", { name: "Save to My Assets" })).toBeNull();
  });

  it("contains full-bleed media inside the asset card", () => {
    const rule = assetStyles.match(/\.v2-asset-entity-card\.v2-asset-discover-card\s*\{([^}]*)\}/);
    const declarations = document.createElement("div").style;

    expect(rule).not.toBeNull();
    declarations.cssText = rule?.[1] ?? "";
    expect(declarations.position).toBe("relative");
    expect(declarations.overflow).toBe("hidden");
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
