import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { EditingInputs } from "./editingModel.ts";
import { EditingPreviewStage } from "./EditingPreviewStage.tsx";
import { fitContainedFrame } from "./editingPreviewSizing.ts";

function asset(
  assetId: string,
  mediaType: ProjectAssetSummaryV2["media_type"],
  options: Partial<ProjectAssetSummaryV2> = {},
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    version_id: null,
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: mediaType,
    source_type: "generated",
    semantic_type: null,
    display_name: assetId,
    mime_type: mediaType === "video" ? "video/mp4" : "audio/mpeg",
    status: "ready",
    size_bytes: 1,
    storage_key: null,
    preview_url: mediaType === "video" ? `/preview/${assetId}` : null,
    media_url: `/media/${assetId}`,
    width: mediaType === "video" ? 1920 : null,
    height: mediaType === "video" ? 1080 : null,
    duration_seconds: 8,
    checksum: `${assetId}-checksum`,
    source_semantic_role: null,
    source_node_id: null,
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: {},
    quality_metadata: {},
    created_at: null,
    ...options,
  };
}

function videoInput(
  referenceId: string,
  videoAsset: ProjectAssetSummaryV2,
  trimStart: number,
  trimEnd: number | null,
): EditingInputs["videos"][number] {
  return {
    referenceId,
    binding: null,
    node: null,
    asset: videoAsset,
    entry: {
      binding_id: null,
      asset_id: videoAsset.asset_id,
      enabled: true,
      trim_start_seconds: trimStart,
      trim_end_seconds: trimEnd,
      volume: 0.8,
      preserve_native_audio: true,
      transition: "cut",
      transition_duration_seconds: 0,
      fit_mode: "fill",
    },
  };
}

function bgmInput(audioAsset: ProjectAssetSummaryV2): NonNullable<EditingInputs["bgm"]> {
  return {
    referenceId: "bgm-1",
    binding: null,
    node: null,
    asset: audioAsset,
    entry: {
      binding_id: null,
      asset_id: audioAsset.asset_id,
      enabled: true,
      trim_start_seconds: 1,
      trim_end_seconds: 5,
      volume: 0.35,
      fade_in_seconds: 0,
      fade_out_seconds: 0,
    },
  };
}

describe("EditingPreviewStage", () => {
  const firstAsset = asset("video-1", "video", { duration_seconds: 8 });
  const secondAsset = asset("video-2", "video", {
    duration_seconds: 10,
    width: 1080,
    height: 1920,
  });

  it.each([
    { container: [800, 200], ratio: 16 / 9, expected: [355.5555555556, 200] },
    { container: [800, 200], ratio: 9 / 16, expected: [112.5, 200] },
    { container: [800, 200], ratio: 1, expected: [200, 200] },
    { container: [200, 800], ratio: 16 / 9, expected: [200, 112.5] },
    { container: [200, 800], ratio: 9 / 16, expected: [200, 200 / (9 / 16)] },
    { container: [200, 800], ratio: 1, expected: [200, 200] },
  ])("fits ratio $ratio inside $container", ({ container, expected, ratio }) => {
    const frame = fitContainedFrame(container[0]!, container[1]!, ratio);

    expect(frame.width).toBeCloseTo(expected[0]!);
    expect(frame.height).toBeCloseTo(expected[1]!);
    expect(frame.width).toBeLessThanOrEqual(container[0]!);
    expect(frame.height).toBeLessThanOrEqual(container[1]!);
    expect(frame.width / frame.height).toBeCloseTo(ratio);
  });

  it("updates explicit contained frame dimensions from the observed stage size", () => {
    let bounds = { width: 800, height: 200 };
    let resizeCallback: ResizeObserverCallback | null = null;
    const observer = { disconnect: vi.fn(), observe: vi.fn(), unobserve: vi.fn() } as unknown as ResizeObserver;
    class ResizeObserverMock {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }

      observe = observer.observe;
      disconnect = observer.disconnect;
    }
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function getBounds() {
      const size = this.classList.contains("agent-editing-preview__canvas")
        ? bounds
        : { width: 0, height: 0 };
      return {
        ...size,
        bottom: size.height,
        left: 0,
        right: size.width,
        top: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      };
    });

    render(
      <EditingPreviewStage
        inputs={inputs}
        outputAspectRatio="9:16"
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={0}
        playing={false}
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );
    const frame = screen.getByTestId("editing-preview-frame");
    expect(frame.style.width).toBe("112.5px");
    expect(frame.style.height).toBe("200px");

    bounds = { width: 200, height: 800 };
    act(() => resizeCallback?.([], observer));
    expect(frame.style.width).toBe("200px");
    expect(parseFloat(frame.style.height)).toBeCloseTo(200 / (9 / 16));
  });
  const inputs: EditingInputs = {
    videos: [
      videoInput("video-1", firstAsset, 1, 4),
      videoInput("video-2", secondAsset, 2, 6),
    ],
    bgm: null,
  };

  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("contains a portrait output frame and never applies the per-clip fill mode", () => {
    render(
      <EditingPreviewStage
        inputs={inputs}
        outputAspectRatio="9:16"
        outputResolution="1920x1080"
        exportedAsset={asset("export", "video", { width: 1, height: 1 })}
        playheadSeconds={0}
        playing={false}
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("editing-preview-frame").getAttribute("style"))
      .toContain("aspect-ratio: 9 / 16");
    expect(screen.getByTestId("editing-preview-video").className)
      .toContain("agent-editing-preview__video--contain");
    expect(screen.getByTestId("editing-preview-video").className).not.toContain("fill");
  });

  it("derives the frame ratio from resolution, export dimensions, source dimensions, then fallback", () => {
    const baseProps = {
      inputs,
      outputAspectRatio: null,
      outputResolution: "1080x1920",
      exportedAsset: null,
      playheadSeconds: 0,
      playing: false,
      muted: false,
      onPlayheadChange: vi.fn(),
      onPlayingChange: vi.fn(),
    };
    const view = render(<EditingPreviewStage {...baseProps} />);
    const frame = screen.getByTestId("editing-preview-frame");

    expect(frame.getAttribute("style")).toContain("aspect-ratio: 1080 / 1920");

    view.rerender(
      <EditingPreviewStage
        {...baseProps}
        inputs={{ videos: [], bgm: null }}
        outputResolution={null}
        exportedAsset={asset("square-export", "video", {
          width: 1024,
          height: 1024,
          media_url: null,
        })}
      />,
    );
    expect(frame.getAttribute("style")).toContain("aspect-ratio: 1024 / 1024");

    view.rerender(<EditingPreviewStage {...baseProps} outputResolution={null} />);
    expect(frame.getAttribute("style")).toContain("aspect-ratio: 1920 / 1080");

    view.rerender(
      <EditingPreviewStage {...baseProps} inputs={{ videos: [], bgm: null }} outputResolution={null} />,
    );
    expect(frame.getAttribute("style")).toContain("aspect-ratio: 16 / 9");
  });

  it("remounts with a new immutable load token at a clip boundary", () => {
    const props = {
      inputs,
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: null,
      playing: false,
      muted: false,
      onPlayheadChange: vi.fn(),
      onPlayingChange: vi.fn(),
    };
    const view = render(<EditingPreviewStage {...props} playheadSeconds={2.5} />);
    const video = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    const firstToken = video.dataset.loadToken;

    expect(video.getAttribute("src")).toBe("/media/video-1");
    expect(video.currentTime).toBeCloseTo(3.5);
    expect(firstToken).toBeTruthy();

    view.rerender(<EditingPreviewStage {...props} playheadSeconds={3} />);

    const nextVideo = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    expect(nextVideo).not.toBe(video);
    expect(nextVideo.dataset.loadToken).not.toBe(firstToken);
    expect(nextVideo.getAttribute("src")).toBe("/media/video-2");
    expect(nextVideo.currentTime).toBeCloseTo(2);
  });

  it("excludes inactive sources from draft boundaries and the BGM timeline clock", () => {
    const disabled = videoInput("video-disabled", asset("video-disabled", "video", {
      duration_seconds: 10,
    }), 0, 10);
    disabled.entry.enabled = false;
    const audioAsset = asset("audio-compressed", "audio", { duration_seconds: 20 });
    const compressedInputs: EditingInputs = {
      videos: [inputs.videos[0]!, disabled, inputs.videos[1]!],
      bgm: bgmInput(audioAsset),
    };

    render(
      <EditingPreviewStage
        inputs={compressedInputs}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={3}
        playing={false}
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );

    const video = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    const audio = screen.getByTestId("editing-preview-bgm") as HTMLAudioElement;
    expect(video.getAttribute("src")).toBe("/media/video-2");
    expect(video.currentTime).toBe(2);
    expect(audio.currentTime).toBe(4);
  });

  it("does not start BGM when there is no playable draft duration", () => {
    const inactive = videoInput("video-disabled", firstAsset, 1, 4);
    inactive.entry.enabled = false;

    render(
      <EditingPreviewStage
        inputs={{
          videos: [inactive],
          bgm: bgmInput(asset("audio-without-video", "audio", { duration_seconds: 20 })),
        }}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={0}
        playing
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );

    expect((screen.getByTestId("editing-preview-bgm") as HTMLAudioElement).currentTime).toBe(0);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("synchronizes enabled BGM trim and volume and pauses it after trim end", () => {
    const audioAsset = asset("audio-1", "audio", { duration_seconds: 20 });
    const withBgm = { ...inputs, bgm: bgmInput(audioAsset) };
    const props = {
      inputs: withBgm,
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: null,
      playing: true,
      muted: false,
      onPlayheadChange: vi.fn(),
      onPlayingChange: vi.fn(),
    };
    const view = render(<EditingPreviewStage {...props} playheadSeconds={2} />);
    const audio = screen.getByTestId("editing-preview-bgm") as HTMLAudioElement;

    expect(audio.getAttribute("src")).toBe("/media/audio-1");
    expect(audio.currentTime).toBeCloseTo(3);
    expect(audio.volume).toBeCloseTo(0.35);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();

    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();
    view.rerender(<EditingPreviewStage {...props} playheadSeconds={4.1} />);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();

    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();
    view.rerender(
      <EditingPreviewStage
        {...props}
        inputs={{
          ...withBgm,
          bgm: { ...withBgm.bgm!, entry: { ...withBgm.bgm!.entry, enabled: false } },
        }}
        playheadSeconds={2}
      />,
    );
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("seeks enabled BGM while paused without trying to autoplay it", () => {
    const audioAsset = asset("audio-paused", "audio", { duration_seconds: 20 });
    render(
      <EditingPreviewStage
        inputs={{ ...inputs, bgm: bgmInput(audioAsset) }}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={2}
        playing={false}
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );

    const audio = screen.getByTestId("editing-preview-bgm") as HTMLAudioElement;
    expect(audio.currentTime).toBeCloseTo(3);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("maps an unbounded BGM playhead through the looped source duration", () => {
    const audioAsset = asset("audio-loop", "audio", { duration_seconds: 3 });
    const bgm = bgmInput(audioAsset);
    bgm.entry.trim_end_seconds = null;
    render(
      <EditingPreviewStage
        inputs={{ ...inputs, bgm }}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={4}
        playing={false}
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );

    const audio = screen.getByTestId("editing-preview-bgm") as HTMLAudioElement;
    expect(audio.loop).toBe(true);
    expect(audio.currentTime).toBeCloseTo(2);
  });

  it("stops playback when the final trimmed clip reaches timeline end", () => {
    const onPlayheadChange = vi.fn();
    const onPlayingChange = vi.fn();
    render(
      <EditingPreviewStage
        inputs={inputs}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={6.9}
        playing
        muted={false}
        onPlayheadChange={onPlayheadChange}
        onPlayingChange={onPlayingChange}
      />,
    );
    const video = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    video.currentTime = 6;
    fireEvent.timeUpdate(video);

    expect(onPlayheadChange).toHaveBeenLastCalledWith(7);
    expect(onPlayingChange).toHaveBeenLastCalledWith(false);
  });

  it("reports a failed source autoplay attempt without surfacing a rejected promise", async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new Error("blocked"));
    const onPlayingChange = vi.fn();

    render(
      <EditingPreviewStage
        inputs={inputs}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={null}
        playheadSeconds={0}
        playing
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={onPlayingChange}
      />,
    );

    await waitFor(() => expect(onPlayingChange).toHaveBeenCalledWith(false));
  });

  it("tolerates BGM play rejection and still follows a controlled pause", async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockImplementation(function play() {
      return this instanceof HTMLAudioElement
        ? Promise.reject(new Error("bgm blocked"))
        : Promise.resolve();
    });
    const onPlayingChange = vi.fn();
    const audioAsset = asset("audio-rejected", "audio", { duration_seconds: 20 });
    const props = {
      inputs: { ...inputs, bgm: bgmInput(audioAsset) },
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: null,
      playheadSeconds: 1,
      muted: false,
      onPlayheadChange: vi.fn(),
      onPlayingChange,
    };
    const view = render(<EditingPreviewStage {...props} playing />);

    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2));
    expect(onPlayingChange).not.toHaveBeenCalledWith(false);

    const audio = screen.getByTestId("editing-preview-bgm") as HTMLAudioElement;
    const pause = vi.spyOn(audio, "pause");
    view.rerender(<EditingPreviewStage {...props} playing={false} />);
    expect(pause).toHaveBeenCalled();
  });

  it("clamps the playhead and stops when trims shorten the sequence", () => {
    const onPlayheadChange = vi.fn();
    const onPlayingChange = vi.fn();
    const props = {
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: null,
      playheadSeconds: 6.5,
      playing: true,
      muted: false,
      onPlayheadChange,
      onPlayingChange,
    };
    const view = render(<EditingPreviewStage {...props} inputs={inputs} />);
    onPlayheadChange.mockClear();
    onPlayingChange.mockClear();

    view.rerender(
      <EditingPreviewStage
        {...props}
        inputs={{ videos: [videoInput("video-1", firstAsset, 1, 3)], bgm: null }}
      />,
    );

    expect(onPlayheadChange).toHaveBeenCalledWith(2);
    expect(onPlayingChange).toHaveBeenCalledWith(false);
  });

  it.each(["disabled", "removed"] as const)(
    "clamps to zero and stops when the final playable clip is %s",
    (change) => {
      const onPlayheadChange = vi.fn();
      const onPlayingChange = vi.fn();
      const active = videoInput("video-final", firstAsset, 0, 4);
      const props = {
        outputAspectRatio: null,
        outputResolution: null,
        exportedAsset: null,
        playheadSeconds: 2,
        playing: true,
        muted: false,
        onPlayheadChange,
        onPlayingChange,
      };
      const view = render(
        <EditingPreviewStage {...props} inputs={{ videos: [active], bgm: null }} />,
      );
      onPlayheadChange.mockClear();
      onPlayingChange.mockClear();

      const videos = change === "removed"
        ? []
        : [{ ...active, entry: { ...active.entry, enabled: false } }];
      view.rerender(
        <EditingPreviewStage {...props} inputs={{ videos, bgm: null }} />,
      );

      expect(onPlayheadChange).toHaveBeenCalledWith(0);
      expect(onPlayingChange).toHaveBeenCalledWith(false);
    },
  );

  it("ignores time and ended events from the previous load after a boundary switch", () => {
    const onPlayheadChange = vi.fn();
    const props = {
      inputs,
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: null,
      playing: true,
      muted: false,
      onPlayheadChange,
      onPlayingChange: vi.fn(),
    };
    const view = render(<EditingPreviewStage {...props} playheadSeconds={2.9} />);
    const video = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    view.rerender(<EditingPreviewStage {...props} playheadSeconds={3} />);
    onPlayheadChange.mockClear();
    video.currentTime = 4;

    fireEvent.timeUpdate(video);
    fireEvent.ended(video);

    expect(onPlayheadChange).not.toHaveBeenCalled();
  });

  it("invalidates stale events when a load is cleared and the same source returns", () => {
    const onPlayheadChange = vi.fn();
    const props = {
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: null,
      playing: false,
      muted: false,
      onPlayheadChange,
      onPlayingChange: vi.fn(),
    };
    const view = render(<EditingPreviewStage {...props} inputs={inputs} playheadSeconds={0} />);
    const staleVideo = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    const staleToken = staleVideo.dataset.loadToken;

    view.rerender(
      <EditingPreviewStage
        {...props}
        inputs={{ videos: [], bgm: null }}
        playheadSeconds={0}
      />,
    );
    onPlayheadChange.mockClear();
    staleVideo.currentTime = 4;
    fireEvent.timeUpdate(staleVideo);
    fireEvent.ended(staleVideo);
    expect(onPlayheadChange).not.toHaveBeenCalled();

    view.rerender(<EditingPreviewStage {...props} inputs={inputs} playheadSeconds={0} />);
    const reloadedVideo = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    expect(reloadedVideo.dataset.loadToken).toBeTruthy();
    expect(reloadedVideo.dataset.loadToken).not.toBe(staleToken);
  });

  it("offers authoritative exported playback without losing the draft playhead", () => {
    const onPlayingChange = vi.fn();
    const props = {
      inputs,
      outputAspectRatio: null,
      outputResolution: null,
      exportedAsset: asset("exported-video", "video"),
      playheadSeconds: 3.5,
      muted: false,
      onPlayheadChange: vi.fn(),
      onPlayingChange,
    };
    const view = render(
      <EditingPreviewStage
        {...props}
        playing={false}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Exported output" }));
    const exported = screen.getByTestId("editing-preview-export") as HTMLVideoElement;
    expect(exported.getAttribute("src")).toBe("/media/exported-video");
    expect(exported.controls).toBe(true);

    onPlayingChange.mockClear();
    view.rerender(<EditingPreviewStage {...props} playing />);
    expect(onPlayingChange).toHaveBeenCalledWith(false);

    fireEvent.click(screen.getByRole("tab", { name: "Draft preview" }));
    const draft = screen.getByTestId("editing-preview-video") as HTMLVideoElement;
    expect(draft.getAttribute("src")).toBe("/media/video-2");
    expect(draft.currentTime).toBeCloseTo(2.5);
    expect(onPlayingChange).toHaveBeenCalledWith(false);
  });

  it("implements linked roving tabs with arrow, Home, and End navigation", () => {
    render(
      <EditingPreviewStage
        inputs={inputs}
        outputAspectRatio={null}
        outputResolution={null}
        exportedAsset={asset("exported-tabs", "video")}
        playheadSeconds={0}
        playing={false}
        muted={false}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );
    const draftTab = screen.getByRole("tab", { name: "Draft preview" });
    const exportTab = screen.getByRole("tab", { name: "Exported output" });

    expect(draftTab.tabIndex).toBe(0);
    expect(exportTab.tabIndex).toBe(-1);
    expect(draftTab.getAttribute("aria-controls")).toBeTruthy();
    expect(exportTab.getAttribute("aria-controls")).toBeTruthy();
    const draftPanel = document.getElementById(draftTab.getAttribute("aria-controls")!);
    const exportPanel = document.getElementById(exportTab.getAttribute("aria-controls")!);
    expect(draftPanel).toBeTruthy();
    expect(exportPanel).toBeTruthy();
    expect(draftPanel?.hidden).toBe(false);
    expect(exportPanel?.hidden).toBe(true);
    let panel = screen.getByRole("tabpanel");
    expect(panel.id).toBe(draftTab.getAttribute("aria-controls"));
    expect(panel.getAttribute("aria-labelledby")).toBe(draftTab.id);

    fireEvent.keyDown(draftTab, { key: "End" });
    expect(exportTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(exportTab);
    panel = screen.getByRole("tabpanel");
    expect(panel.id).toBe(exportTab.getAttribute("aria-controls"));
    expect(panel.getAttribute("aria-labelledby")).toBe(exportTab.id);
    expect(draftPanel?.hidden).toBe(true);
    expect(exportPanel?.hidden).toBe(false);

    fireEvent.keyDown(exportTab, { key: "ArrowRight" });
    expect(draftTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(draftTab);

    fireEvent.keyDown(draftTab, { key: "ArrowLeft" });
    expect(exportTab.getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(exportTab, { key: "Home" });
    expect(draftTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(draftTab);
  });
});
