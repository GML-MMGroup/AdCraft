import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { RecommendedSceneHologram } from "./RecommendedSceneHologram.tsx";

const ASSETS: AgentAssetBrowserItem[] = [1, 2].map((index) => ({
  id: `recommended:recommended-v1-scene-00${index}`,
  assetId: `scene-${index}`,
  source: "recommended",
  mediaType: "image",
  displayName: `Scene ${index}`,
  previewUrl: `/preview-${index}.png`,
  mediaUrl: `/scene-${index}.png`,
  status: "ready",
  tags: ["scene"],
  identity: {
    source: "recommended",
    assetId: `scene-${index}`,
    entityId: `recommended-v1-scene-00${index}`,
    versionId: `version-${index}`,
  },
  projectAsset: null,
}));

describe("RecommendedSceneHologram", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("pauses only while the projection is hovered or its viewer is open", () => {
    const onOpen = vi.fn();
    const view = render(
      <RecommendedSceneHologram
        assets={ASSETS}
        buttonRef={vi.fn()}
        onOpen={onOpen}
        viewerOpen={false}
      />,
    );

    const firstProjection = screen.getByRole("button", { name: "Open original scene Scene 1" });
    fireEvent.mouseEnter(firstProjection);
    act(() => vi.advanceTimersByTime(18_000));
    expect(screen.getByText("Scene 1", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();

    fireEvent.mouseLeave(firstProjection);
    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.getByText("Scene 2", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();

    const secondProjection = screen.getByRole("button", { name: "Open original scene Scene 2" });
    fireEvent.click(secondProjection);
    expect(onOpen).toHaveBeenCalledWith(ASSETS[1], secondProjection);
    view.rerender(
      <RecommendedSceneHologram
        assets={ASSETS}
        buttonRef={vi.fn()}
        onOpen={onOpen}
        viewerOpen
      />,
    );
    act(() => vi.advanceTimersByTime(18_000));
    expect(screen.getByText("Scene 2", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();

    view.rerender(
      <RecommendedSceneHologram
        assets={ASSETS}
        buttonRef={vi.fn()}
        onOpen={onOpen}
        viewerOpen={false}
      />,
    );
    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.getByText("Scene 1", { selector: ".recommended-scenes-hologram__name" })).toBeTruthy();
  });
});
