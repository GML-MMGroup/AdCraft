import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import BgmDirectorAnimation, {
  BGM_DIRECTOR_MOTION_PROGRAM,
} from "./BgmDirectorAnimation.tsx";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

const NOTE_PARTS = [
  "score-note-1",
  "score-note-2",
  "score-note-3",
  "score-note-4",
  "score-note-5",
] as const;
const WAVEFORM_PARTS = ["waveform-static", "waveform-strip"] as const;
const WAVEFORM_PULSE_PARTS = [
  "waveform-pulse-1",
  "waveform-pulse-2",
  "waveform-pulse-3",
  "waveform-pulse-4",
  "waveform-pulse-5",
] as const;
const WORKING_PARTS = [
  ...WAVEFORM_PARTS,
  ...WAVEFORM_PULSE_PARTS,
  ...NOTE_PARTS,
] as const;

describe("BgmDirectorAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it("renders one clipped, permanently yellow periodic waveform and a valid five-line score", () => {
    const { container } = render(<BgmDirectorAnimation motionState="idle" />);
    const artwork = assertRoleArtworkContract(container, "bgm-director", [
      "base",
      "headphones",
      "central-waveform",
      "staff",
      "score-notes",
      "baton",
    ]);

    expect(artwork.querySelectorAll('[data-part="staff"] [data-staff-line]'))
      .toHaveLength(5);
    expect(artwork.querySelector('[data-part="central-note"]')).toBeNull();
    expect(artwork.querySelectorAll('[data-part^="wave-sample-"]')).toHaveLength(0);
    const waveform = artwork.querySelector('[data-part="central-waveform"]')!;
    const waveformWindow = artwork.querySelector<SVGRectElement>(
      "[data-waveform-window]",
    )!;
    expect(waveformWindow).not.toBeNull();
    expect({
      x: waveformWindow.getAttribute("x"),
      y: waveformWindow.getAttribute("y"),
      width: waveformWindow.getAttribute("width"),
      height: waveformWindow.getAttribute("height"),
    }).toEqual({ x: "168", y: "156", width: "176", height: "128" });

    const layers = WAVEFORM_PARTS.map((part) => (
      waveform.querySelector<SVGGElement>(`[data-part="${part}"]`)!
    ));
    expect(layers.every(Boolean)).toBe(true);
    expect(layers.every((layer) => layer.dataset.waveformTileWidth === "176"))
      .toBe(true);
    expect(layers.every((layer) => layer.dataset.waveformCopyCount === "3"))
      .toBe(true);
    const layerPulses = layers.map((layer) => (
      [...layer.querySelectorAll<SVGGElement>("[data-waveform-pulse]")]
    ));
    expect(layerPulses.map((pulses) => pulses.length)).toEqual([5, 5]);
    expect(layerPulses[0].map((pulse) => (
      pulse.querySelector("path")?.getAttribute("d")
    ))).toEqual(layerPulses[1].map((pulse) => (
      pulse.querySelector("path")?.getAttribute("d")
    )));
    const primaryPulsePaths = layerPulses[0].map((pulse) => (
      pulse.querySelector("path")?.getAttribute("d") ?? ""
    ));
    expect(primaryPulsePaths[1]).toContain("C234 225 236 180 246 220");
    expect(primaryPulsePaths[2]).toContain(
      "C252 188 256 251 265 244 C274 237 275 145 285 220",
    );
    expect(primaryPulsePaths[3]).toContain(
      "C292 170 298 263 307 249 C316 235 319 190 326 220",
    );
    expect(layerPulses.flat().every((pulse) => (
      pulse.querySelector("path")?.getAttribute("stroke") === "#FFB323"
    ))).toBe(true);
    expect(layerPulses.flat().reduce((curveCount, pulse) => (
      curveCount + (pulse.querySelector("path")?.getAttribute("d")?.match(/C/g)?.length ?? 0)
    ), 0)).toBe(54);
    expect(layerPulses[0].every((pulse) => pulse.getAttribute("data-part") === null))
      .toBe(true);
    expect(layerPulses[1].map((pulse) => pulse.dataset.part))
      .toEqual(WAVEFORM_PULSE_PARTS);
    expect(layerPulses.flat().every((pulse) => (
      pulse.style.transformBox === "view-box"
      && pulse.style.transformOrigin === "0px 220px"
      && pulse.style.transform.startsWith("scaleY(")
    ))).toBe(true);
    expect(waveform.querySelector('[data-part^="waveform-lobe-"]')).toBeNull();
    expect(waveform.querySelector('[data-part="waveform-active"]')).toBeNull();
    expect(artwork.querySelector('[data-part="waveform-reveal-window"]')).toBeNull();
    expect(artwork.querySelectorAll("clipPath")).toHaveLength(1);
    expect(layers[0].style.transform).toBe("translateX(-176px)");
    expect(layers[1].style.transform).toBe("translateX(-176px)");
    expect(layers[0].getAttribute("opacity")).toBe("1");
    expect(layers[1].getAttribute("opacity")).toBe("0");
    const notes = [...artwork.querySelectorAll<SVGGElement>(
      '[data-part="score-notes"] > [data-part]',
    )];
    expect(notes).toHaveLength(5);
    expect(notes.every((note) => note.querySelector("ellipse[data-note-head]")))
      .toBe(true);
    expect(notes.every((note) => note.querySelector("line[data-note-stem]")))
      .toBe(true);
    expect(notes.every((note) => note.querySelector("path[data-note-flag]")))
      .toBe(true);
    expect(notes.map((note) => Number(
      note.querySelector("ellipse[data-note-head]")?.getAttribute("cy"),
    ))).toEqual([446, 422, 434, 458, 438]);
    expect(artwork.querySelector('[data-part="beat-points"]')).toBeNull();
  });

  it("crossfades to a rightward strip with a full-cycle pulse traveling left to right", () => {
    expect(BGM_DIRECTOR_MOTION_PROGRAM.workingEntryTimeMs).toBe(0);
    expect(BGM_DIRECTOR_MOTION_PROGRAM.working.map(({ part }) => part))
      .toEqual(WORKING_PARTS);
    expect(BGM_DIRECTOR_MOTION_PROGRAM.waiting).toEqual([]);

    const [staticTrack, stripTrack, ...remainingTracks] =
      BGM_DIRECTOR_MOTION_PROGRAM.working;
    expect(staticTrack.keyframes).toEqual([
      { offset: 0, opacity: 0 },
      { offset: 1, opacity: 0 },
    ]);
    expect(stripTrack.keyframes).toEqual([
      { offset: 0, opacity: 1, transform: "translateX(-176px)" },
      { offset: 1, opacity: 1, transform: "translateX(0px)" },
    ]);
    for (const track of [staticTrack, stripTrack]) {
      expect(track.options).toMatchObject({
        duration: 3_000,
        iterations: Infinity,
        easing: "linear",
      });
    }

    const pulseTracks = remainingTracks.slice(0, WAVEFORM_PULSE_PARTS.length);
    expect(pulseTracks.map(({ part }) => part)).toEqual(WAVEFORM_PULSE_PARTS);
    expect(pulseTracks.map((track) => {
      const peakFrame = track.keyframes.reduce((peak, frame) => (
        Number(String(frame.transform).match(/scaleY\(([\d.]+)\)/)?.[1] ?? 0)
          > Number(String(peak.transform).match(/scaleY\(([\d.]+)\)/)?.[1] ?? 0)
          ? frame
          : peak
      ));
      return peakFrame.offset;
    })).toEqual([0, 5 / 24, 10 / 24, 16 / 24, 20 / 24]);
    for (const track of pulseTracks) {
      expect(track.keyframes).toHaveLength(25);
      expect(track.keyframes[0]?.offset).toBe(0);
      expect(track.keyframes.at(-1)?.offset).toBe(1);
      expect(track.keyframes[0]?.transform)
        .toBe(track.keyframes.at(-1)?.transform);
      expect(track.keyframes.every((frame) => (
        typeof frame.offset === "number"
        && String(frame.transform).startsWith("scaleY(")
      ))).toBe(true);
      const scales = track.keyframes.map((frame) => Number(
        String(frame.transform).match(/scaleY\(([\d.]+)\)/)?.[1],
      ));
      expect(Math.min(...scales)).toBe(0.62);
      expect(Math.max(...scales)).toBe(1.38);
      expect(track.options).toMatchObject({
        duration: 3_000,
        iterations: Infinity,
        easing: "linear",
      });
    }
  });

  it("preserves five score-note hops with strictly ascending peak phases", () => {
    const noteTracks = BGM_DIRECTOR_MOTION_PROGRAM.working.slice(
      2 + WAVEFORM_PULSE_PARTS.length,
    );
    expect(noteTracks).toHaveLength(5);
    for (const track of noteTracks) {
      expect(track.keyframes[0], track.part).toMatchObject({
        offset: 0,
        opacity: 0.78,
        transform: "translateY(0px)",
      });
      expect(track.keyframes.at(-1), track.part).toMatchObject({
        offset: 1,
        opacity: 0.78,
        transform: "translateY(0px)",
      });
      expect(track.options, track.part).toMatchObject({
        duration: 3_000,
        iterations: Infinity,
        easing: "linear",
      });
    }
    const peakOffsets = noteTracks.map((track) => {
      const peak = track.keyframes.find((frame) => (
        frame.transform === "translateY(-12px)"
      ));
      expect(peak, track.part).toBeDefined();
      return Number(peak?.offset);
    });
    expect(peakOffsets).toEqual([0.18, 0.33, 0.48, 0.63, 0.78]);
    for (let index = 1; index < peakOffsets.length; index += 1) {
      expect(peakOffsets[index]).toBeGreaterThan(peakOffsets[index - 1]);
    }
  });

  it("keeps the baton static and connects the program to the lifecycle", () => {
    const { container } = render(<BgmDirectorAnimation motionState="working" />);
    expect(BGM_DIRECTOR_MOTION_PROGRAM.working.map(({ part }) => part))
      .not.toContain("baton");
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: container.querySelector("svg") }),
      "working",
      BGM_DIRECTOR_MOTION_PROGRAM,
    );
  });
});
