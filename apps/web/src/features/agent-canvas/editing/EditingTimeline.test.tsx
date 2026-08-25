import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EditingBgmEntryV2,
  EditingVideoEntryV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import type { EditingBoundInput, EditingInputs } from "./editingModel.ts";
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
      exportRunning={false}
      {...callbacks}
    />,
  );
  return { ...callbacks, inputs, ...view };
}

beforeEach(() => {
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

    expect(onStageVideo).toHaveBeenCalledWith("video-1", { trim_start_seconds: 1.4 });
    expect(onCommitStagedManifest).not.toHaveBeenCalled();

    fireEvent.pointerUp(window, { pointerId: 1, clientX: 140 });
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 140 });
    expect(onCommitStagedManifest).toHaveBeenCalledTimes(1);
  });

  it("commits a changed drag once on pointer cancellation", () => {
    const { onCommitStagedManifest } = renderTimeline();
    const handle = screen.getByRole("slider", { name: "Trim end Shot 1" });

    fireEvent.pointerDown(handle, { pointerId: 2, clientX: 200 });
    fireEvent.pointerMove(window, { pointerId: 2, clientX: 160 });
    fireEvent.pointerCancel(window, { pointerId: 2, clientX: 160 });

    expect(onCommitStagedManifest).toHaveBeenCalledTimes(1);
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

    expect((videoTrack.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width)
      .toBe((track.querySelector(".agent-editing-timeline__lane") as HTMLElement).style.width);
    expect(within(track).getByRole("checkbox", { name: "Enabled" })).toBeTruthy();
    expect(within(track).getByRole("slider", { name: "BGM volume" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Trim start" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Trim end" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Fade in" })).toBeTruthy();
    expect(within(track).getByRole("spinbutton", { name: "Fade out" })).toBeTruthy();
  });
});

describe("EditingTimelineViewport", () => {
  it("uses fit-all as the minimum and resets zoom from the controls and ruler", () => {
    render(
      <EditingTimelineViewport duration={20} playheadSeconds={2} onPlayheadChange={vi.fn()}>
        {(state) => <output data-testid="pixels-per-second">{state.pixelsPerSecond}</output>}
      </EditingTimelineViewport>,
    );

    expect(screen.getByTestId("pixels-per-second").textContent).toBe("40");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(Number(screen.getByTestId("pixels-per-second").textContent)).toBeGreaterThan(40);

    fireEvent.click(screen.getByRole("button", { name: "Fit timeline" }));
    expect(screen.getByTestId("pixels-per-second").textContent).toBe("40");

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.doubleClick(screen.getByTestId("timeline-ruler"));
    expect(screen.getByTestId("pixels-per-second").textContent).toBe("40");
    expect((screen.getByRole("slider", { name: "Timeline zoom" }) as HTMLInputElement).min).toBe("40");
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
    fireEvent.wheel(scroller, { clientX: 524, ctrlKey: true, deltaY: -100 });
    expect(Number(screen.getByTestId("content-width").textContent)).toBeGreaterThan(widthBefore);
    expect(scroller.scrollLeft).toBeGreaterThan(120);
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
