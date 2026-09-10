import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { CharacterDesignerArtwork } from "./CharacterDesignerArtwork.tsx";
import { CHARACTER_ROUTES } from "./characterDesignerGeometry.ts";
import CharacterDesignerAnimation, { CHARACTER_DESIGNER_MOTION_PROGRAM as program } from "./CharacterDesignerAnimation.tsx";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({ useAgentRoleMotion: vi.fn() }));

const pose = ({ transform = "none", opacity = 1 }: Keyframe) => ({ transform, opacity });

describe("Character Designer character study", () => {
  it("draws an open jacket with linework and no filled garment planes", () => {
    const { container } = render(<CharacterDesignerAnimation motionState="idle" />);
    expect(container.querySelector('[data-garment="front"]')).toBeNull();
    expect(container.querySelector('[data-garment="body"]')).toBeNull();
    expect(container.querySelector('[data-garment="inner"]')).toBeNull();
    expect(container.querySelectorAll("[data-collar-fabric]")).toHaveLength(0);
    expect(container.querySelector('[data-garment="outline"]')?.getAttribute("fill")).toBe("none");
  });

  it("keeps short lapels continuous and monotonic along their reveal axes", () => {
    const lapels = CHARACTER_ROUTES.filter((route) => route.id.endsWith("-lapel"));
    expect(lapels).toHaveLength(2);
    expect(lapels[0].samples.at(-1)!.point).toEqual(lapels[1].samples[0].point);
    for (const route of lapels) {
      expect(Math.max(...route.samples.map((sample) => sample.point[1]))).toBeLessThanOrEqual(390);
      route.samples.slice(1).forEach((sample, i) => {
        expect(sample.point[route.axis]).toBeGreaterThanOrEqual(route.samples[i].point[route.axis]);
      });
    }
  });

  it("keeps lapels as open strokes instead of closed fabric shapes", () => {
    const { container } = render(<CharacterDesignerAnimation motionState="idle" />);
    for (const route of CHARACTER_ROUTES.filter((route) => route.id.endsWith("-lapel"))) {
      expect(container.querySelector(`[data-collar-fabric="${route.id}"]`)).toBeNull();
      expect(container.querySelector(`[data-completed-stroke="${route.id}"]`)
        ?.getAttribute("d")).toBe(route.path);
    }
  });

  it("draws every contour in its intrinsic color and width instead of a uniform yellow overlay", () => {
    const { container } = render(<CharacterDesignerAnimation motionState="idle" />);
    const active = container.querySelectorAll("[data-active-stroke]");
    expect(active).toHaveLength(9);
    for (const path of active) {
      const id = path.getAttribute("data-active-stroke");
      const complete = container.querySelector(`[data-completed-stroke="${id}"]`);
      expect(complete, `${id} must have a canonical completed path`).not.toBeNull();
      expect(path.getAttribute("stroke")).toBe(complete!.getAttribute("stroke"));
      expect(path.getAttribute("stroke-width")).toBe(complete!.getAttribute("stroke-width"));
      if (id !== "right-lapel") expect(path.getAttribute("stroke")).not.toBe("#FFB323");
    }
    expect(container.querySelector('[data-completed-stroke="right-lapel"]')?.getAttribute("stroke")).toBe("#FFB323");
    expect(container.querySelector('[data-completed-stroke="right-lapel"]')?.getAttribute("stroke-width")).toBe("5");
    expect(container.querySelector('[data-pencil-grip]')?.getAttribute("fill")).toBe("#FFB323");
    for (const layer of container.querySelectorAll('[data-part^="ink-"]')) expect(layer.getAttribute("stroke")).toBeNull();
  });

  it("ships a static poster from the exact same canonical Idle geometry", () => {
    const expected = renderToStaticMarkup(<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><CharacterDesignerArtwork idPrefix="character-poster" /></svg>);
    const poster = readFileSync("public/imgs/agent-role-icons/character-designer-20260906-line-art.svg", "utf8").trim();
    expect(poster).toBe(expected);
    expect(poster).not.toMatch(/<script|<animate|<foreignObject/);
  });
  it("contains three authored regions and a visible pencil, with no competing face animation", () => {
    const { container } = render(<CharacterDesignerAnimation motionState="idle" />);
    const svg = assertRoleArtworkContract(container, "character-designer", ["base", "design-pencil"]);
    for (const region of ["hair", "face", "collar"]) {
      expect(svg.querySelector(`[data-design-region="${region}"]`)).not.toBeNull();
    }
    expect(svg.querySelector('[data-part="eyelid-half"]')).toBeNull();
    expect(svg.querySelectorAll("filter, image, animate")).toHaveLength(0);
    expect(svg.querySelector('[data-part="design-pencil"]')?.getAttribute("style")).toContain("transform-origin: 0px 0px");
  });

  it("constructs once, then refines continuously from the identical finished pose", () => {
    expect(program.workingIntro?.length).toBeGreaterThan(0);
    for (const track of program.workingIntro!) {
      expect(track.options.duration).toBe(4800);
      expect(track.options.iterations).toBe(1);
      const loop = program.working.find((candidate) => candidate.part === track.part)!;
      expect(pose(track.keyframes.at(-1)!)).toEqual(pose(loop.keyframes[0]));
    }
    for (const track of program.working) {
      expect(track.options.duration).toBe(4800);
      expect(track.options.iterations).toBe(Infinity);
      expect(pose(track.keyframes[0])).toEqual(pose(track.keyframes.at(-1)!));
    }
    expect(program.waiting).toEqual([]);
  });

  it("keeps the pencil visible through every drawing and return pose", () => {
    for (const tracks of [program.workingIntro!, program.working]) {
      const pencil = tracks.find((track) => track.part === "design-pencil")!;
      expect(pencil).toBeDefined();
      expect(pencil.keyframes.length).toBeGreaterThan(30);
      expect(pencil.keyframes.every((frame) => Number(frame.opacity) === 1)).toBe(true);
    }
  });

  it("keeps future strokes hidden until the exact contact instant", () => {
    const masks = program.workingIntro?.filter((track) => track.part.startsWith("reveal-")) ?? [];
    expect(masks.length).toBeGreaterThan(3);
    for (const track of masks) {
      expect(track.keyframes[0].opacity).toBe(0);
      const visible = track.keyframes.findIndex((frame) => Number(frame.opacity) > 0);
      if (visible < 0) continue;
      expect(track.keyframes[visible - 1].opacity).toBe(0);
      expect(track.keyframes[visible - 1].offset).toBe(track.keyframes[visible].offset);
    }
  });

  it("uses a bounded set of ordered transform/opacity tracks", () => {
    for (const tracks of [program.workingIntro!, program.working]) {
      expect(tracks.length).toBeLessThanOrEqual(20);
      for (const track of tracks) {
        const offsets = track.keyframes.map((frame) => Number(frame.offset));
        expect(offsets).toEqual([...offsets].sort((a, b) => a - b));
        expect(offsets[0]).toBe(0);
        expect(offsets.at(-1)).toBe(1);
        for (const frame of track.keyframes) {
          expect(Object.keys(frame).every((key) => ["offset", "transform", "opacity", "easing"].includes(key))).toBe(true);
        }
      }
    }
  });
});
