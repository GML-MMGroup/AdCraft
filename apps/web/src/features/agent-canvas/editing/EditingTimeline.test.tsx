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
    media_url: null,
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
      timelineDuration={8}
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
    const pixelsPerSecond = Number((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).value);

    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 100 });
    fireEvent.pointerMove(window, { pointerId: 1, clientX: 140 });

    expect(onStageVideo).toHaveBeenCalledWith("video-1", {
      trim_start_seconds: Math.round((1 + 40 / pixelsPerSecond) * 1_000) / 1_000,
    });
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
        timelineDuration={16}
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

  it("keeps the first selected start target reachable at the fit-left boundary", () => {
    renderTimeline({
      inputs: { videos: [video("video-1", 1), video("video-2", 2)], bgm: null },
      selectedReferenceId: "video-1",
    });
    const scroller = screen.getByTestId("timeline-scroll-viewport");
    const handle = screen.getByRole("slider", { name: "Trim start Shot 1" });
    const clip = handle.parentElement as HTMLElement;
    const playhead = document.querySelector(".agent-editing-timeline-viewport__playhead") as HTMLElement;
    const pixelsPerSecond = Number((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).value);
    const viewportBounds = scroller.getBoundingClientRect();
    const timeOrigin = parseFloat(playhead.style.left) - 2 * pixelsPerSecond;
    const targetLeft = timeOrigin + parseFloat(clip.style.left) + parseFloat(handle.style.left);

    expect(scroller.scrollLeft).toBe(0);
    expect(targetLeft).toBeGreaterThanOrEqual(124);
    expect(targetLeft + parseFloat(handle.style.width)).toBeLessThanOrEqual(viewportBounds.right);
  });

  it("keeps the final selected end target reachable at the zoomed-right boundary", () => {
    renderTimeline({
      inputs: { videos: [video("video-1", 1), video("video-2", 2)], bgm: null },
      selectedReferenceId: "video-2",
    });
    const scroller = screen.getByTestId("timeline-scroll-viewport");
    const content = document.querySelector(".agent-editing-timeline-viewport__content") as HTMLElement;
    const handle = screen.getByRole("slider", { name: "Trim end Shot 2" });
    const clip = handle.parentElement as HTMLElement;
    const playhead = document.querySelector(".agent-editing-timeline-viewport__playhead") as HTMLElement;

    fireEvent.change(screen.getByRole("slider", { name: "Timeline zoom" }), { target: { value: "100" } });
    fireEvent.wheel(scroller, { deltaY: 2_000 });

    const pixelsPerSecond = Number((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).value);
    const viewportBounds = scroller.getBoundingClientRect();
    const timeOrigin = parseFloat(playhead.style.left) - 2 * pixelsPerSecond;
    const targetRight = timeOrigin
      + parseFloat(clip.style.left)
      + parseFloat(clip.style.width)
      + parseFloat(handle.style.width)
      - scroller.scrollLeft;

    expect(scroller.scrollLeft).toBe(parseFloat(content.style.width) - viewportBounds.width);
    expect(targetRight - parseFloat(handle.style.width)).toBeGreaterThanOrEqual(124);
    expect(targetRight).toBeLessThanOrEqual(viewportBounds.right);
  });
});

describe("EditingTimeline retained controls", () => {
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

  it("keeps all BGM controls in the waveform track", () => {
    renderTimeline({ inputs: { videos: [video("video-1", 1)], bgm: bgm() } });
    const videoTrack = screen.getByRole("group", { name: "Video track" });
    const track = screen.getByRole("group", { name: "Audio track" });
    const ruler = document.querySelector(".agent-editing-timeline-viewport__ruler") as HTMLElement;

    expect((videoTrack.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width)
      .toBe((track.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width);
    expect((videoTrack.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width)
      .toBe(ruler.style.width);
    expect(within(track).getByRole("checkbox", { name: "Enabled" })).toBeTruthy();
    expect(within(track).getByRole("slider", { name: "BGM volume" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Trim start" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Trim end" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Fade in" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Fade out" })).toBeTruthy();
  });

  it("disables trim and clip properties during export while leaving zoom and seek usable", () => {
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

    const zoomLevel = screen.getByLabelText("Timeline zoom level");
    const zoomBefore = zoomLevel.textContent;
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(zoomLevel.textContent).not.toBe(zoomBefore);

    fireEvent.change(screen.getByRole("slider", { name: "Timeline playhead" }), { target: { value: "4" } });
    expect(view.onPlayheadChange).toHaveBeenLastCalledWith(4);
  });
});

describe("EditingTimelineViewport", () => {
  it("uses fit-all as the minimum and resets zoom from the controls and ruler", () => {
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={vi.fn()}>
        {(state) => <output data-testid="pixels-per-second">{state.pixelsPerSecond}</output>}
      </EditingTimelineViewport>,
    );

    expect(screen.getByTestId("pixels-per-second").textContent).toBe("38.2");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(Number(screen.getByTestId("pixels-per-second").textContent)).toBeGreaterThan(38.2);

    fireEvent.click(screen.getByRole("button", { name: "Fit timeline" }));
    expect(screen.getByTestId("pixels-per-second").textContent).toBe("38.2");

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.doubleClick(screen.getByTestId("timeline-ruler"));
    expect(screen.getByTestId("pixels-per-second").textContent).toBe("38.2");
    expect((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).min).toBe("38.2");
  });

  it("zooms around the pointer with Ctrl-wheel and uses ordinary wheel for horizontal navigation", () => {
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={vi.fn()}>
        {(state) => <output data-testid="content-width">{state.contentWidth}</output>}
      </EditingTimelineViewport>,
    );
    const scroller = screen.getByTestId("timeline-scroll-viewport");

    expect(fireEvent.wheel(scroller, { deltaY: 120 })).toBe(true);
    expect(scroller.scrollLeft).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.wheel(scroller, { deltaY: 120 });
    expect(scroller.scrollLeft).toBe(120);

    const widthBefore = Number(screen.getByTestId("content-width").textContent);
    const zoomBefore = Number((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).value);
    const pointerOffset = 524 - 124 - 18;
    const anchorBefore = (scroller.scrollLeft + pointerOffset) / zoomBefore;
    fireEvent.wheel(scroller, { clientX: 524, ctrlKey: true, deltaY: -100 });
    const zoomAfter = Number((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).value);
    const anchorAfter = (scroller.scrollLeft + pointerOffset) / zoomAfter;

    expect(Number(screen.getByTestId("content-width").textContent)).toBeGreaterThan(widthBefore);
    expect(scroller.scrollLeft).toBeGreaterThan(120);
    expect(anchorAfter).toBeCloseTo(anchorBefore, 8);
  });

  it("retains ruler and keyboard seeking", () => {
    const onPlayheadChange = vi.fn();
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={onPlayheadChange}>
        {() => null}
      </EditingTimelineViewport>,
    );

    fireEvent.click(screen.getByTestId("timeline-ruler"), { clientX: 524 });
    expect(onPlayheadChange).toHaveBeenCalledWith(10);

    fireEvent.keyDown(screen.getByRole("slider", { name: "Timeline playhead" }), { key: "ArrowRight" });
    expect(onPlayheadChange).toHaveBeenLastCalledWith(3);
  });

  it("seeks from a scrolled ruler content rect without counting scroll twice", () => {
    const onPlayheadChange = vi.fn();
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={onPlayheadChange}>
        {() => null}
      </EditingTimelineViewport>,
    );
    const scroller = screen.getByTestId("timeline-scroll-viewport");
    const ruler = screen.getByTestId("timeline-ruler");

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.wheel(scroller, { deltaY: 120 });
    vi.spyOn(ruler, "getBoundingClientRect").mockReturnValue({
      bottom: 27,
      height: 27,
      left: -120,
      right: 884,
      top: 0,
      width: 1_004,
      x: -120,
      y: 0,
      toJSON: () => ({}),
    });

    const pixelsPerSecond = Number((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).value);
    fireEvent.click(ruler, { clientX: -120 + 124 + 18 + 10 * pixelsPerSecond });

    expect(onPlayheadChange).toHaveBeenLastCalledWith(10);
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

  it("requests frames for visible and adjacent clips but not distant clips", () => {
    const inputs = {
      videos: Array.from({ length: 8 }, (_, index) => video(`video-${index + 1}`, index + 1)),
      bgm: null,
    };
    renderTimeline({ inputs, selectedReferenceId: "video-1" });

    fireEvent.change(screen.getByRole("slider", { name: "Timeline zoom" }), { target: { value: "100" } });
    fireEvent.wheel(screen.getByTestId("timeline-scroll-viewport"), { deltaY: 2_000 });

    const latestRequests = new Map<string, VideoFrameRequest>();
    for (const [request] of useVideoFrameStripMock.mock.calls) latestRequests.set(request.assetId, request);
    expect(Array.from({ length: 8 }, (_, index) => latestRequests.get(`video-${index + 1}`)?.active))
      .toEqual([false, true, true, true, true, false, false, false]);
  });
});
