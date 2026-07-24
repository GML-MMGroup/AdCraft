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

  it("routes Final Composition to a dedicated playable card without prompt editing", () => {
    const onOpenVideo = vi.fn();
    const onOpenSlotEditor = vi.fn();
    const finalItem = normalizeWorkflowItemV2({
      item_id: "final-item",
      node_id: "final-composition",
      item_type: "final_composition",
      display_name: "Final Composition",
      status: "failed",
      lifecycle_state: "active",
    });
    const finalSlot = normalizeWorkflowSlotV2({
      slot_id: "final-slot",
      node_id: "final-composition",
      item_id: "final-item",
      slot_type: "final_video",
      media_type: "video",
      required: true,
      status: "failed",
      selected_asset_id: "final-asset",
      selected_version_id: "final-version",
    });
    const finalAsset = normalizeAssetVersionV2({
      asset_id: "final-asset",
      version_id: "final-version",
      media_type: "video",
      source_type: "generated",
      semantic_type: "final_video",
      public_url: "/media/final.mp4",
      thumbnail_path: "/media/final-poster.jpg",
    });

    render(
      <V2RegionCardPreview
        title="Final Composition"
        items={[finalItem]}
        slots={[finalSlot]}
        assetVersions={[finalAsset]}
        runtime={{
          workflow_id: "workflow-1",
          status: "partial_failed",
          completed_node_ids: [],
          failed_node_ids: ["final-composition"],
          completed_item_ids: [],
          failed_item_ids: ["final-item"],
          completed_slot_ids: [],
          blocked_slot_ids: [],
          skipped_slot_ids: [],
          node_runtime: {},
          item_runtime: {},
          slot_runtime: {
            "final-slot": {
              status: "failed",
              error: null,
              waiting_reason: null,
              provider_task_id: null,
              selected_asset_id: "final-asset",
              selected_version_id: "final-version",
              current_working_asset_id: null,
              current_working_version_id: null,
              attempt_count: 1,
              metadata: { generation_error_code: "provider_failed" },
            },
          },
          events_cursor: 1,
        }}
        onOpenSlotEditor={onOpenSlotEditor}
        onOpenStoryboardVideoPreview={onOpenVideo}
      />,
    );

    expect(screen.getByLabelText("Final Composition card")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Play final video" }));
    expect(onOpenVideo).toHaveBeenCalledWith(expect.objectContaining({
      src: expect.stringContaining("/media/final.mp4"),
      title: "Final video",
    }));
    expect(onOpenSlotEditor).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /edit.*prompt/i })).toBeNull();
    expect(screen.getByText("failed")).toBeTruthy();
  });
});
