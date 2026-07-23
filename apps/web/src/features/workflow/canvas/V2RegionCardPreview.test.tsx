import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { normalizeAssetVersionV2, normalizeWorkflowItemV2, normalizeWorkflowSlotV2 } from "../../../api/v2Normalizers.ts";
import { V2RegionCardPreview } from "./V2RegionCardPreview.tsx";

function bgmItem(overrides: Record<string, unknown> = {}) {
  return normalizeWorkflowItemV2({
    item_id: "bgm-item",
    node_id: "bgm",
    item_type: "bgm",
    display_name: "Background music",
    status: "completed",
    lifecycle_state: "active",
    ...overrides,
  });
}

function bgmSlot(overrides: Record<string, unknown> = {}) {
  return normalizeWorkflowSlotV2({
    slot_id: "bgm-slot",
    node_id: "bgm",
    item_id: "bgm-item",
    slot_type: "bgm_audio",
    media_type: "audio",
    required: true,
    status: "completed",
    selected_asset_id: "bgm-asset",
    ...overrides,
  });
}

function bgmAsset() {
  return normalizeAssetVersionV2({
    asset_id: "bgm-asset",
    version_id: "bgm-version",
    media_type: "audio",
    source_type: "generated",
    semantic_type: "bgm",
    public_url: "/bgm.mp3",
    duration_seconds: 12,
  });
}

afterEach(cleanup);

describe("V2RegionCardPreview", () => {
  it("routes a canonical BGM item to the dedicated BGM card", () => {
    const onOpenSlotEditor = vi.fn();
    const item = bgmItem();
    const slot = bgmSlot();
    const asset = bgmAsset();

    render(
      <V2RegionCardPreview
        title="Background music"
        items={[item]}
        slots={[slot]}
        assetVersions={[asset]}
        onOpenSlotEditor={onOpenSlotEditor}
      />,
    );

    expect(screen.getByLabelText("BGM card")).toBeTruthy();
    expect(screen.queryByText("1 items")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit BGM prompt" }));
    expect(onOpenSlotEditor).toHaveBeenCalledWith("bgm-slot");
  });

  it("does not route a noncanonical item with a BGM-shaped slot to the BGM card", () => {
    render(
      <V2RegionCardPreview
        title="Other region"
        items={[bgmItem({ node_id: "voice", item_type: "voiceover" })]}
        slots={[bgmSlot({ node_id: "voice" })]}
        assetVersions={[bgmAsset()]}
      />,
    );

    expect(screen.queryByLabelText("BGM card")).toBeNull();
    expect(screen.getByText("1 items")).toBeTruthy();
  });

  it("keeps a mixed BGM and image region on the generic card path", () => {
    const imageItem = normalizeWorkflowItemV2({
      item_id: "image-item",
      node_id: "product",
      item_type: "product",
      display_name: "Product image",
      status: "completed",
      lifecycle_state: "active",
    });
    const imageSlot = normalizeWorkflowSlotV2({
      slot_id: "image-slot",
      node_id: "product",
      item_id: "image-item",
      slot_type: "product_main_image",
      media_type: "image",
      required: true,
      status: "completed",
      selected_asset_id: "image-asset",
    });
    const imageAsset = normalizeAssetVersionV2({
      asset_id: "image-asset",
      version_id: "image-version",
      media_type: "image",
      source_type: "generated",
      semantic_type: "product",
      public_url: "/image.png",
      width: 800,
      height: 800,
    });

    render(
      <V2RegionCardPreview
        title="Mixed region"
        items={[bgmItem(), imageItem]}
        slots={[bgmSlot(), imageSlot]}
        assetVersions={[bgmAsset(), imageAsset]}
      />,
    );

    expect(screen.queryByLabelText("BGM card")).toBeNull();
    expect(screen.getByText("2 items")).toBeTruthy();
    expect(screen.getByRole("img", { name: "product_main_image" })).toBeTruthy();
  });

  it("keeps a mixed BGM and Storyboard region on the generic card path", () => {
    const storyboardItem = normalizeWorkflowItemV2({
      item_id: "shot-item",
      node_id: "storyboard",
      item_type: "shot",
      display_name: "Opening shot",
      status: "completed",
      lifecycle_state: "active",
      shot_id: "shot-1",
    });
    const storyboardSlot = normalizeWorkflowSlotV2({
      slot_id: "shot-image-slot",
      node_id: "storyboard",
      item_id: "shot-item",
      slot_type: "shot_main_image",
      media_type: "image",
      required: true,
      status: "completed",
      selected_asset_id: "shot-image-asset",
    });
    const storyboardAsset = normalizeAssetVersionV2({
      asset_id: "shot-image-asset",
      version_id: "shot-image-version",
      media_type: "image",
      source_type: "generated",
      semantic_type: "storyboard",
      public_url: "/shot.png",
      width: 1280,
      height: 720,
    });

    render(
      <V2RegionCardPreview
        title="Mixed storyboard region"
        items={[bgmItem(), storyboardItem]}
        slots={[bgmSlot(), storyboardSlot]}
        assetVersions={[bgmAsset(), storyboardAsset]}
      />,
    );

    expect(screen.queryByLabelText("BGM card")).toBeNull();
    expect(screen.getByRole("button", { name: "Show storyboard images" })).toBeTruthy();
  });
});
