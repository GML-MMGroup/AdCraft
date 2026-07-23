import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { normalizeAssetVersionV2, normalizeWorkflowItemV2, normalizeWorkflowRuntimeV2, normalizeWorkflowSlotV2 } from "../../../api/v2Normalizers.ts";
import { buildV2RegionFunctionalModel } from "../v2/region/v2RegionFunctionalModel.ts";
import { V2BgmFunctionalCard } from "./V2BgmFunctionalCard.tsx";

type CardOptions = {
  selectedUrl?: string;
  workingUrl?: string;
  workingVersionId?: string;
  runtimeStatus?: string;
  runtimeErrorCode?: string;
  runtimeMetadataErrorCode?: string;
  runtimeMessage?: string;
  audioMode?: string;
  selectedIdentity?: boolean;
  workingIdentity?: boolean;
  onOpen?: (slotId: string) => void;
  onSelect?: (slotId: string, versionId: string) => void;
  onDiscard?: (slotId: string) => void;
};

function renderCard(options: CardOptions = {}) {
  const workingVersionId = options.workingVersionId ?? "working-version";
  const slot = normalizeWorkflowSlotV2({
    slot_id: "bgm-slot",
    node_id: "bgm",
    item_id: "bgm-item",
    slot_type: "bgm_audio",
    media_type: "audio",
    required: true,
    status: options.runtimeStatus ?? "completed",
    selected_asset_id: options.selectedUrl || options.selectedIdentity ? "selected-asset" : null,
    current_working_version_id: options.workingUrl || options.workingIdentity ? workingVersionId : null,
  });
  const item = normalizeWorkflowItemV2({
    item_id: "bgm-item",
    node_id: "bgm",
    item_type: "bgm",
    display_name: "Background music",
    item_prompt: "A warm upbeat track",
    status: options.runtimeStatus ?? "completed",
    lifecycle_state: "active",
    metadata: options.audioMode ? { audio_mode: options.audioMode } : {},
  });
  const assetVersions = [
    ...(options.selectedUrl ? [audioAsset("selected-asset", "selected-version", options.selectedUrl)] : []),
    ...(options.workingUrl ? [audioAsset("working-asset", workingVersionId, options.workingUrl)] : []),
  ];
  const runtime = options.runtimeErrorCode || options.runtimeMetadataErrorCode
    ? normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-1",
        slot_runtime: {
          "bgm-slot": {
            status: options.runtimeStatus ?? "failed",
            ...(options.runtimeErrorCode
              ? { error: { code: options.runtimeErrorCode, message: options.runtimeMessage ?? "Provider failed", stage: "provider" } }
              : {}),
            ...(options.runtimeMetadataErrorCode
              ? { generation_error_code: options.runtimeMetadataErrorCode }
              : {}),
          },
        },
      })
    : undefined;
  const model = buildV2RegionFunctionalModel({ title: "BGM", items: [item], slots: [slot], assetVersions, runtime });
  const onOpen = options.onOpen ?? vi.fn();
  const onSelect = options.onSelect ?? vi.fn();
  const onDiscard = options.onDiscard ?? vi.fn();

  return {
    ...render(
      <V2BgmFunctionalCard
        item={model.items[0]}
        audioMode={options.audioMode}
        openSlotId={null}
        onOpenSlotEditor={onOpen}
        onSelectSlotVersion={onSelect}
        onDiscardSlotWorkingVersion={onDiscard}
      />,
    ),
    onOpen,
    onSelect,
    onDiscard,
  };
}

function audioAsset(assetId: string, versionId: string, publicUrl: string) {
  return normalizeAssetVersionV2({
    asset_id: assetId,
    version_id: versionId,
    media_type: "audio",
    source_type: "generated",
    semantic_type: "bgm",
    public_url: publicUrl,
    duration_seconds: 16,
  });
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function play(this: HTMLMediaElement) {
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("V2BgmFunctionalCard", () => {
  it("keeps Selected playable while showing a Working candidate", () => {
    renderCard({ selectedUrl: "/selected.mp3", workingUrl: "/working.mp3" });

    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByLabelText("Working soundtrack candidate audio player")).toBeTruthy();
  });

  it("opens the composer only from the prompt surface", () => {
    const onOpen = vi.fn();
    renderCard({ selectedUrl: "/selected.mp3", onOpen });

    fireEvent.click(screen.getByRole("button", { name: "Edit BGM prompt" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Play Selected soundtrack" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("selects and discards a Working candidate explicitly", () => {
    const onSelect = vi.fn();
    const onDiscard = vi.fn();
    renderCard({ workingUrl: "/working.mp3", workingVersionId: "ver-working", onSelect, onDiscard });

    fireEvent.click(screen.getByRole("button", { name: "Use Working soundtrack" }));
    expect(onSelect).toHaveBeenCalledWith("bgm-slot", "ver-working");
    fireEvent.click(screen.getByRole("button", { name: "Discard Working soundtrack" }));
    expect(onDiscard).toHaveBeenCalledWith("bgm-slot");
  });

  it("keeps the Selected player visible while BGM generation is running", () => {
    renderCard({ selectedUrl: "/selected.mp3", runtimeStatus: "running" });

    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByLabelText("Generating")).toBeTruthy();
  });

  it("keeps the Selected player when explicit audio mode disables generation", () => {
    const onOpen = vi.fn();
    renderCard({ selectedUrl: "/selected.mp3", runtimeStatus: "skipped", audioMode: "none", onOpen });

    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByText("Audio disabled")).toBeTruthy();
    expect(screen.getByText("The retained soundtrack will not be used in the final video.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Edit BGM prompt" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Edit BGM prompt" }));
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("soft-skips an unconfigured BGM provider without exposing provider details", () => {
    renderCard({
      selectedUrl: "/selected.mp3",
      runtimeStatus: "skipped",
      runtimeErrorCode: "v2_bgm_provider_unconfigured_soft_skip",
      runtimeMessage: "provider host /internal/providers is unavailable",
    });

    expect(screen.getByText("BGM provider not configured")).toBeTruthy();
    expect(screen.getByText("The final video can continue without music.")).toBeTruthy();
    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Edit BGM prompt" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/internal\/providers/)).toBeNull();
  });

  it("recognizes the canonical generation error code from runtime metadata", () => {
    renderCard({
      selectedUrl: "/selected.mp3",
      runtimeStatus: "skipped",
      runtimeMetadataErrorCode: "v2_bgm_provider_unconfigured_soft_skip",
    });

    expect(screen.getByText("BGM provider not configured")).toBeTruthy();
    expect(screen.getByText("The final video can continue without music.")).toBeTruthy();
  });

  it("uses canonical failure copy without exposing provider diagnostics", () => {
    renderCard({
      runtimeStatus: "failed",
      runtimeErrorCode: "provider_failed",
      runtimeMessage: '{"hostname":"provider-10.internal","request_id":"req-4815","detail":"retry failed"}',
    });

    expect(screen.getByText("BGM generation failed")).toBeTruthy();
    expect(screen.getByText("Try generating the soundtrack again.")).toBeTruthy();
    expect(screen.queryByText(/provider-10\.internal/)).toBeNull();
    expect(screen.queryByText(/req-4815/)).toBeNull();
    expect(screen.queryByText(/retry failed/)).toBeNull();
  });

  it("keeps the Selected player when BGM generation fails", () => {
    renderCard({ selectedUrl: "/selected.mp3", runtimeStatus: "failed", runtimeErrorCode: "provider_failed" });

    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByText("BGM generation failed")).toBeTruthy();
  });

  it("shows selected metadata syncing instead of an empty state", () => {
    renderCard({ selectedIdentity: true });

    expect(screen.getByText("Selected asset metadata syncing")).toBeTruthy();
    expect(screen.queryByText("No soundtrack selected")).toBeNull();
  });

  it("shows working metadata syncing when the candidate identity has no URL", () => {
    renderCard({ selectedUrl: "/selected.mp3", workingIdentity: true });

    expect(screen.getByText("Working asset metadata syncing")).toBeTruthy();
    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
  });

  it("does not expose a stale working asset when the current version has not hydrated", () => {
    const item = normalizeWorkflowItemV2({
      item_id: "bgm-item",
      node_id: "bgm",
      item_type: "bgm",
      display_name: "Background music",
      status: "completed",
      lifecycle_state: "active",
    });
    const slot = normalizeWorkflowSlotV2({
      slot_id: "bgm-slot",
      node_id: "bgm",
      item_id: "bgm-item",
      slot_type: "bgm_audio",
      media_type: "audio",
      required: true,
      status: "completed",
      current_working_asset_id: "working-asset",
      current_working_version_id: "working-version-current",
    });
    const model = buildV2RegionFunctionalModel({
      title: "BGM",
      items: [item],
      slots: [slot],
      assetVersions: [audioAsset("working-asset", "working-version-older", "/stale-working.mp3")],
    });

    render(<V2BgmFunctionalCard item={model.items[0]} openSlotId={null} />);

    expect(screen.getByText("Working asset metadata syncing")).toBeTruthy();
    expect(screen.queryByLabelText("Working soundtrack candidate audio player")).toBeNull();
    expect(screen.queryByRole("button", { name: "Use Working soundtrack" })).toBeNull();
  });

  it("keeps a newer working version on the selected asset in metadata syncing", () => {
    const item = normalizeWorkflowItemV2({
      item_id: "bgm-item",
      node_id: "bgm",
      item_type: "bgm",
      display_name: "Background music",
      status: "completed",
      lifecycle_state: "active",
    });
    const slot = normalizeWorkflowSlotV2({
      slot_id: "bgm-slot",
      node_id: "bgm",
      item_id: "bgm-item",
      slot_type: "bgm_audio",
      media_type: "audio",
      required: true,
      status: "completed",
      selected_asset_id: "asset-a",
      current_working_asset_id: "asset-a",
      current_working_version_id: "version-2",
    });
    const model = buildV2RegionFunctionalModel({
      title: "BGM",
      items: [item],
      slots: [slot],
      assetVersions: [audioAsset("asset-a", "version-1", "/selected-version-1.mp3")],
    });

    render(<V2BgmFunctionalCard item={model.items[0]} openSlotId={null} />);

    expect(screen.getByLabelText("Selected soundtrack audio player")).toBeTruthy();
    expect(screen.getByText("Working asset metadata syncing")).toBeTruthy();
    expect(screen.queryByLabelText("Working soundtrack candidate audio player")).toBeNull();
  });

  it("keeps Selected and Working distinct when they share an asset id", () => {
    const item = normalizeWorkflowItemV2({
      item_id: "bgm-item",
      node_id: "bgm",
      item_type: "bgm",
      display_name: "Background music",
      status: "completed",
      lifecycle_state: "active",
    });
    const slot = normalizeWorkflowSlotV2({
      slot_id: "bgm-slot",
      node_id: "bgm",
      item_id: "bgm-item",
      slot_type: "bgm_audio",
      media_type: "audio",
      required: true,
      status: "completed",
      selected_asset_id: "asset-a",
      selected_version_id: "version-1",
      current_working_asset_id: "asset-a",
      current_working_version_id: "version-2",
    });
    const model = buildV2RegionFunctionalModel({
      title: "BGM",
      items: [item],
      slots: [slot],
      assetVersions: [
        audioAsset("asset-a", "version-1", "/selected-version-1.mp3"),
        audioAsset("asset-a", "version-2", "/working-version-2.mp3"),
      ],
    });

    render(<V2BgmFunctionalCard item={model.items[0]} openSlotId={null} />);

    expect(screen.getByLabelText("Selected soundtrack audio player").querySelector("audio")?.getAttribute("src")).toContain("/selected-version-1.mp3");
    expect(screen.getByLabelText("Working soundtrack candidate audio player").querySelector("audio")?.getAttribute("src")).toContain("/working-version-2.mp3");
    expect(screen.getByRole("button", { name: "Use Working soundtrack" })).toBeTruthy();
  });

  it("does not substitute Working when the exact Selected version is still hydrating", () => {
    const item = normalizeWorkflowItemV2({
      item_id: "bgm-item",
      node_id: "bgm",
      item_type: "bgm",
      display_name: "Background music",
      status: "completed",
      lifecycle_state: "active",
    });
    const slot = normalizeWorkflowSlotV2({
      slot_id: "bgm-slot",
      node_id: "bgm",
      item_id: "bgm-item",
      slot_type: "bgm_audio",
      media_type: "audio",
      required: true,
      status: "completed",
      selected_asset_id: "asset-a",
      selected_version_id: "version-1",
      current_working_asset_id: "asset-a",
      current_working_version_id: "version-2",
    });
    const model = buildV2RegionFunctionalModel({
      title: "BGM",
      items: [item],
      slots: [slot],
      assetVersions: [audioAsset("asset-a", "version-2", "/working-version-2.mp3")],
    });

    render(<V2BgmFunctionalCard item={model.items[0]} openSlotId={null} />);

    expect(screen.getByText("Selected asset metadata syncing")).toBeTruthy();
    expect(screen.queryByLabelText("Selected soundtrack audio player")).toBeNull();
    expect(screen.getByLabelText("Working soundtrack candidate audio player")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use Working soundtrack" })).toBeTruthy();
  });

  it("shows an empty state when no soundtrack exists", () => {
    renderCard();

    expect(screen.getByText("No soundtrack selected")).toBeTruthy();
  });
});
