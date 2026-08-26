import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EditingBgmEntryV2,
  EditingVideoEntryV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import type { EditingBoundInput, EditingInputs } from "./editingModel.ts";
import type { VideoFrameRequest } from "./useVideoFrameStrip.ts";

const useVideoFrameStripMock = vi.hoisted(() => vi.fn((_request: VideoFrameRequest) => []));
vi.mock("./useVideoFrameStrip.ts", () => ({ useVideoFrameStrip: useVideoFrameStripMock }));

import { EditingTimeline } from "./EditingTimeline.tsx";
import { EditingTimelineViewport } from "./EditingTimelineViewport.tsx";
import { frameStripActiveIndices } from "./editingTimelineVisibility.ts";

function asset(
  assetId: string,
  mediaType: ProjectAssetSummaryV2["media_type"],
  durationSeconds: number,
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    media_type: mediaType,
    source_type: "generated",
    display_name: mediaType === "video" ? `Shot ${assetId.split("-").at(-1)}` : "Campaign BGM",
    mime_type: mediaType === "video" ? "video/mp4" : "audio/mpeg",
    status: "ready",
    preview_url: mediaType === "video" ? `/preview/${assetId}.jpg` : null,
    media_url: `/media/${assetId}`,
    width: mediaType === "video" ? 1920 : null,
    height: mediaType === "video" ? 1080 : null,
    duration_seconds: durationSeconds,
    checksum: `${assetId}-checksum`,
  };
}

function video(referenceId: string, index: number, overrides: Partial<EditingVideoEntryV2> = {}): EditingBoundInput<EditingVideoEntryV2> {
  return {
    referenceId,
    binding: null,
    node: null,
    asset: asset(`video-${index}`, "video", 10),
    entry: {
      binding_id: referenceId,
      asset_id: null,
      enabled: true,
      trim_start_seconds: 1,
      trim_end_seconds: 9,
      volume: 1,
      preserve_native_audio: true,
      transition: "fade",
      transition_duration_seconds: 0.5,
      fit_mode: "fit",
      ...overrides,
    },
  };
}

function bgm(): EditingBoundInput<EditingBgmEntryV2> {
  return {
    referenceId: "bgm-1",
    binding: null,
    node: null,
    asset: asset("audio-1", "audio", 24),
    entry: {
      binding_id: "bgm-1",
      asset_id: null,
      enabled: true,
      trim_start_seconds: 2,
      trim_end_seconds: 20,
      volume: 0.4,
      fade_in_seconds: 1,
      fade_out_seconds: 2,
    },
  };
}

function renderTimeline(options: {
  exportRunning?: boolean;
  inputs?: EditingInputs;
  selectedReferenceId?: string | null;
} = {}) {
  const callbacks = {
    onCommitStagedManifest: vi.fn(),
    onDiscardStagedManifest: vi.fn(),
    onMoveVideo: vi.fn(),
    onPlayheadChange: vi.fn(),
    onSelectReference: vi.fn(),
    onSetBgm: vi.fn(),
    onSetBgmVolume: vi.fn(),
    onStageVideo: vi.fn(),
    onUpdateVideo: vi.fn(),
  };
  const inputs = options.inputs ?? { videos: [video("video-1", 1)], bgm: null };
  const view = render(
    <EditingTimeline
      inputs={inputs}
      playheadSeconds={2}
      selectedReferenceId={options.selectedReferenceId === undefined ? "video-1" : options.selectedReferenceId}
      exportRunning={options.exportRunning ?? false}
      {...callbacks}
    />,
  );
  return { ...callbacks, inputs, ...view };
}

beforeEach(() => {
  useVideoFrameStripMock.mockClear();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    bottom: 200,
    height: 200,
    left: 0,
    right: 924,
    top: 0,
    width: 924,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("EditingTimeline direct trim", () => {
  it("stages pointer movement and commits once when the drag ends", () => {
    const { onCommitStagedManifest, onStageVideo } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim start Shot 1" });

    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 100 });
    fireEvent.pointerMove(window, { pointerId: 1, clientX: 140 });

    expect(onStageVideo).toHaveBeenCalledWith("video-1", { trim_start_seconds: expect.any(Number) });
    expect(onCommitStagedManifest).not.toHaveBeenCalled();

    fireEvent.pointerUp(window, { pointerId: 1, clientX: 140 });
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 140 });
    expect(onCommitStagedManifest).toHaveBeenCalledTimes(1);
  });

  it("discards a changed drag on pointer cancellation", () => {
    const { onCommitStagedManifest, onDiscardStagedManifest } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim end Shot 1" });

    fireEvent.pointerDown(handle, { pointerId: 2, clientX: 200 });
    fireEvent.pointerMove(window, { pointerId: 2, clientX: 160 });
    fireEvent.pointerCancel(window, { pointerId: 2, clientX: 160 });

    expect(onDiscardStagedManifest).toHaveBeenCalledTimes(1);
    expect(onCommitStagedManifest).not.toHaveBeenCalled();
  });

  it("discards staged values when a drag returns to its original trim", () => {
    const { onCommitStagedManifest, onDiscardStagedManifest, onStageVideo } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim start Shot 1" });

    fireEvent.pointerDown(handle, { pointerId: 5, clientX: 100 });
    fireEvent.pointerMove(window, { pointerId: 5, clientX: 140 });
    fireEvent.pointerMove(window, { pointerId: 5, clientX: 100 });
    fireEvent.pointerUp(window, { pointerId: 5, clientX: 100 });

    expect(onStageVideo).toHaveBeenLastCalledWith("video-1", { trim_start_seconds: 1 });
    expect(onDiscardStagedManifest).toHaveBeenCalledTimes(1);
    expect(onCommitStagedManifest).not.toHaveBeenCalled();
  });

  it("discards the current drag on Escape without committing", () => {
    const { onCommitStagedManifest, onDiscardStagedManifest } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim start Shot 1" });

    fireEvent.pointerDown(handle, { pointerId: 3, clientX: 100 });
    fireEvent.pointerMove(window, { pointerId: 3, clientX: 140 });
    fireEvent.keyDown(window, { key: "Escape" });

    expect(onDiscardStagedManifest).toHaveBeenCalledTimes(1);
    expect(onCommitStagedManifest).not.toHaveBeenCalled();
  });

  it("discards a changed drag when its clip unmounts", () => {
    const { onDiscardStagedManifest, unmount } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim start Shot 1" });

    fireEvent.pointerDown(handle, { pointerId: 4, clientX: 100 });
    fireEvent.pointerMove(window, { pointerId: 4, clientX: 140 });
    unmount();

    expect(onDiscardStagedManifest).toHaveBeenCalledTimes(1);
  });

  it("stages and commits one keyboard trim action at the requested step", () => {
    const { onCommitStagedManifest, onStageVideo } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim start Shot 1" });

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onStageVideo).toHaveBeenLastCalledWith("video-1", { trim_start_seconds: 1.1 });
    expect(onCommitStagedManifest).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
    expect(onStageVideo).toHaveBeenLastCalledWith("video-1", { trim_start_seconds: 2.1 });
    expect(onCommitStagedManifest).toHaveBeenCalledTimes(2);
  });

  it("shows trim handles only on the selected clip", () => {
    const inputs = { videos: [video("video-1", 1), video("video-2", 2)], bgm: null };
    const { rerender, ...callbacks } = renderTimeline({ inputs, selectedReferenceId: "video-1" });

    expect(screen.getAllByRole("slider", { name: /^Trim (start|end) / })).toHaveLength(2);
    expect(screen.queryByRole("slider", { name: "Trim start Shot 2" })).toBeNull();

    rerender(
      <EditingTimeline
        inputs={inputs}
        playheadSeconds={2}
        selectedReferenceId="video-2"
        exportRunning={false}
        {...callbacks}
      />,
    );
    expect(screen.queryByRole("slider", { name: "Trim start Shot 1" })).toBeNull();
    expect(screen.getByRole("slider", { name: "Trim start Shot 2" })).toBeTruthy();
  });

  it("keeps two outward trim targets independent on a narrower-than-target clip", () => {
    const short = video("video-short", 1, { trim_start_seconds: 0, trim_end_seconds: null });
    short.asset = asset("video-1", "video", 0.001);
    renderTimeline({ inputs: { videos: [short, video("video-2", 2)], bgm: null }, selectedReferenceId: "video-short" });

    const start = screen.getByRole("slider", { name: "Trim start Shot 1" });
    const end = screen.getByRole("slider", { name: "Trim end Shot 1" });
    const clip = start.parentElement as HTMLElement;
    const surface = clip.querySelector(".agent-editing-timeline-clip__surface") as HTMLElement;

    expect(parseFloat(clip.style.width)).toBeLessThan(1);
    expect(clip.classList.contains("agent-editing-timeline-clip")).toBe(true);
    expect(surface.parentElement).toBe(clip);
    expect(surface.contains(start)).toBe(false);
    expect(surface.contains(end)).toBe(false);
    expect(clip.style.overflow).toBe("visible");
    expect(clip.style.zIndex).toBe("8");
    expect(surface.style.overflow).toBe("hidden");
    expect(start.style.width).toBe("18px");
    expect(start.style.left).toBe("-18px");
    expect(end.style.width).toBe("18px");
    expect(end.style.left).toBe("100%");
  });

  it("publishes trim slider bounds that enforce the effective minimum duration", () => {
    const { unmount } = renderTimeline();
    const start = screen.getByRole("slider", { name: "Trim start Shot 1" });
    const end = screen.getByRole("slider", { name: "Trim end Shot 1" });

    expect(start.getAttribute("aria-valuemax")).toBe("8.5");
    expect(end.getAttribute("aria-valuemin")).toBe("1.5");
    unmount();

    const short = video("video-short", 1, { trim_start_seconds: 0, trim_end_seconds: null });
    short.asset = asset("video-1", "video", 0.25);
    renderTimeline({ inputs: { videos: [short], bgm: null }, selectedReferenceId: "video-short" });

    expect(screen.getByRole("slider", { name: "Trim start Shot 1" }).getAttribute("aria-valuemax")).toBe("0");
    expect(screen.getByRole("slider", { name: "Trim end Shot 1" }).getAttribute("aria-valuemin")).toBe("0.25");
  });

  it("keeps both selected trim handles inside the fixed-fit timeline", () => {
    renderTimeline({
      inputs: { videos: [video("video-1", 1), video("video-2", 2)], bgm: null },
      selectedReferenceId: "video-2",
    });
    const scroller = screen.getByTestId("timeline-scroll-viewport");
    const viewportBounds = scroller.getBoundingClientRect();
    const start = screen.getByRole("slider", { name: "Trim start Shot 2" });
    const handle = screen.getByRole("slider", { name: "Trim end Shot 2" });
    expect(start.parentElement?.style.overflow).toBe("visible");
    expect(handle.parentElement?.style.overflow).toBe("visible");
    expect(viewportBounds.width).toBeGreaterThan(0);
  });
});

describe("EditingTimeline retained controls", () => {
  it("keeps inactive sources off the timed track while preserving selection and enable controls", () => {
    const active = video("video-active", 1, { trim_start_seconds: 1, trim_end_seconds: 5 });
    const disabled = video("video-disabled", 2, { enabled: false });
    const unavailable = video("video-unavailable", 3);
    unavailable.asset = { ...unavailable.asset!, media_url: null };
    const view = renderTimeline({
      inputs: { videos: [active, disabled, unavailable], bgm: null },
      selectedReferenceId: "video-disabled",
    });

    const videoTrack = screen.getByRole("group", { name: "Video track" });
    expect(videoTrack.querySelectorAll(".agent-editing-timeline-clip")).toHaveLength(1);
    expect(screen.getByRole("slider", { name: "Timeline playhead" }).getAttribute("aria-valuemax")).toBe("4");

    const inactive = screen.getByRole("region", { name: "Inactive sources" });
    expect(within(inactive).getByText("Disabled")).toBeTruthy();
    expect(within(inactive).getByText("Media unavailable")).toBeTruthy();
    expect(within(inactive).getByRole("button", { name: "Inspect Shot 3" })).toBeTruthy();
    expect(screen.getByRole("toolbar", { name: "Clip properties" })).toBeTruthy();

    fireEvent.click(within(inactive).getByRole("checkbox", { name: "Enable Shot 2" }));
    expect(view.onUpdateVideo).toHaveBeenCalledWith("video-disabled", { enabled: true });
    fireEvent.click(within(inactive).getByRole("button", { name: "Inspect Shot 3" }));
    expect(view.onSelectReference).toHaveBeenCalledWith("video-unavailable");
  });

  it("replaces the selected clip form while retaining non-trim clip properties", () => {
    const view = renderTimeline();

    expect(screen.queryByLabelText("Selected clip")).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Trim start" })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Trim end" })).toBeNull();

    const properties = screen.getByRole("toolbar", { name: "Clip properties" });
    expect(within(properties).getByRole("checkbox", { name: "Enabled" })).toBeTruthy();
    expect(within(properties).getByRole("slider", { name: "Volume" })).toBeTruthy();
    expect(within(properties).getByRole("checkbox", { name: "Source audio" })).toBeTruthy();
    expect(within(properties).getByRole("combobox", { name: "Transition" })).toBeTruthy();
    expect(within(properties).getByRole("spinbutton", { name: "Transition duration" })).toBeTruthy();
    expect(within(properties).getByRole("combobox", { name: "Fit" })).toBeTruthy();
    expect(within(properties).getByRole("button", { name: "Move Shot 1 earlier" })).toBeTruthy();
    expect(within(properties).getByRole("button", { name: "Move Shot 1 later" })).toBeTruthy();

    fireEvent.change(within(properties).getByRole("slider", { name: "Volume" }), { target: { value: "0.5" } });
    expect(view.onUpdateVideo).toHaveBeenCalledWith("video-1", { volume: 0.5 });
  });

  it("keeps BGM controls below the Audio Track label and trims with direct handles", () => {
    renderTimeline({ inputs: { videos: [video("video-1", 1)], bgm: bgm() } });
    const videoTrack = screen.getByRole("group", { name: "Video track" });
    const track = screen.getByRole("group", { name: "Audio track" });
    const ruler = document.querySelector(".agent-editing-timeline-viewport__ruler") as HTMLElement;

    expect((videoTrack.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width)
      .toBe((track.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width);
    expect((videoTrack.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width)
      .toBe(ruler.style.width);
    const controls = within(track).getByRole("region", { name: "Audio track controls" });
    expect(track.querySelector('img[src="/icon/arcticons--ambient-music-mod.svg"]')).toBeTruthy();
    expect(within(controls).getByRole("checkbox", { name: "Enabled" })).toBeTruthy();
    expect(within(controls).getByRole("slider", { name: "BGM volume" })).toBeTruthy();
    expect(within(track).queryByRole("spinbutton", { name: "Trim start" })).toBeNull();
    expect(within(track).queryByRole("spinbutton", { name: "Trim end" })).toBeNull();
    expect(within(track).getByRole("slider", { name: "Trim start BGM" })).toBeTruthy();
    expect(within(track).getByRole("slider", { name: "Trim end BGM" })).toBeTruthy();
    expect(within(track).queryByText("Campaign BGM")).toBeNull();
    expect(within(track).queryByRole("button", { name: "Mute BGM" })).toBeNull();
    expect(track.querySelector(".agent-editing-timeline__track-label")?.contains(controls)).toBe(true);
    expect(track.querySelector(".agent-editing-timeline__lane")?.contains(controls)).toBe(false);
  });

  it("disables trim and clip properties during export while leaving direct playhead seek usable", () => {
    const view = renderTimeline({ exportRunning: true });
    const start = screen.getByRole("slider", { name: "Trim start Shot 1" });
    const properties = screen.getByRole("toolbar", { name: "Clip properties" });

    expect(start.getAttribute("aria-disabled")).toBe("true");
    expect(start.getAttribute("tabindex")).toBe("-1");
    for (const control of properties.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>("button, input, select")) {
      expect(control.disabled).toBe(true);
    }

    fireEvent.pointerDown(start, { pointerId: 9, clientX: 100 });
    fireEvent.pointerMove(window, { pointerId: 9, clientX: 140 });
    fireEvent.pointerUp(window, { pointerId: 9, clientX: 140 });
    expect(view.onStageVideo).not.toHaveBeenCalled();
    expect(view.onCommitStagedManifest).not.toHaveBeenCalled();

    const playhead = screen.getByRole("slider", { name: "Timeline playhead" });
    expect(playhead.hasAttribute("disabled")).toBe(false);
    expect(screen.getByTestId("timeline-ruler").getAttribute("tabindex")).toBe("0");
    fireEvent.pointerDown(playhead, { pointerId: 12, clientX: 200 });
    fireEvent.pointerMove(window, { pointerId: 12, clientX: 300 });
    expect(view.onPlayheadChange).toHaveBeenLastCalledWith(expect.any(Number));
  });
});

describe("EditingTimelineViewport", () => {
  it("removes zoom controls and the bottom scrubber", () => {
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={vi.fn()}>
        {(state) => <output data-testid="pixels-per-second">{state.pixelsPerSecond}</output>}
      </EditingTimelineViewport>,
    );

    expect(screen.getByTestId("pixels-per-second").textContent).toBe("38.2");
    expect(screen.queryByRole("slider", { name: "Timeline zoom" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Fit timeline" })).toBeNull();
    expect(document.querySelector(".agent-editing-timeline__scrubber")).toBeNull();
  });

  it("makes the playhead itself draggable and keeps ruler seeking", () => {
    const onPlayheadChange = vi.fn();
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={onPlayheadChange}>
        {() => null}
      </EditingTimelineViewport>,
    );
    fireEvent.click(screen.getByTestId("timeline-ruler"), { clientX: 524 });
    expect(onPlayheadChange).toHaveBeenCalledWith(10);

    const playhead = screen.getByRole("slider", { name: "Timeline playhead" });
    expect(playhead.tagName).not.toBe("INPUT");
    expect(playhead.style.zIndex).toBe("20");
    fireEvent.pointerDown(playhead, { pointerId: 13, clientX: 200 });
    fireEvent.pointerMove(window, { pointerId: 13, clientX: 524 });
    fireEvent.pointerUp(window, { pointerId: 13, clientX: 524 });
    expect(onPlayheadChange).toHaveBeenLastCalledWith(10);
    fireEvent.keyDown(playhead, { key: "ArrowRight" });
    expect(onPlayheadChange).toHaveBeenLastCalledWith(3);
  });

});

describe("frame strip visibility", () => {
  it("activates visible clips and one adjacent clip on each side", () => {
    const segments = [
      { referenceId: "a", timelineStart: 0, timelineEnd: 2, sourceStart: 0, sourceEnd: 2 },
      { referenceId: "b", timelineStart: 2, timelineEnd: 4, sourceStart: 0, sourceEnd: 2 },
      { referenceId: "c", timelineStart: 4, timelineEnd: 6, sourceStart: 0, sourceEnd: 2 },
      { referenceId: "d", timelineStart: 6, timelineEnd: 8, sourceStart: 0, sourceEnd: 2 },
      { referenceId: "e", timelineStart: 8, timelineEnd: 10, sourceStart: 0, sourceEnd: 2 },
    ];

    expect([...frameStripActiveIndices(segments, 4.25, 5.75)]).toEqual([1, 2, 3]);
  });

});
