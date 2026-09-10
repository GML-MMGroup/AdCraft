import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import SceneDesignerAnimation, {
  SCENE_DESIGNER_MOTION_PROGRAM,
} from "./SceneDesignerAnimation.tsx";
import { SceneDesignerArtwork } from "./SceneDesignerArtwork.tsx";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

function trackFor(part: string): AgentRoleMotionTrack {
  const track = SCENE_DESIGNER_MOTION_PROGRAM.working
    .find((candidate) => candidate.part === part);
  expect(track).toBeDefined();
  return track!;
}

function stubReducedMotion(matches: boolean): void {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

describe("SceneDesignerAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
    stubReducedMotion(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds a line-art set without material planes, shadows, or broad glow", () => {
    const { container } = render(<SceneDesignerAnimation motionState="idle" />);
    const artwork = assertRoleArtworkContract(container, "scene-designer", [
      "construction-scene",
      "completed-scene",
      "scene-reveal",
      "construction-hide",
      "scene-scan",
      "scene-accent",
    ]);

    expect(artwork.querySelector('[data-part="construction-scene"]')
      ?.getAttribute("opacity")).toBe("0.24");
    expect(artwork.querySelector('[data-part="construction-scene"]')
      ?.getAttribute("mask")).toMatch(/^url\(#.+\)$/);
    expect(artwork.querySelector('[data-part="completed-scene"]')
      ?.getAttribute("mask")).toMatch(/^url\(#.+\)$/);
    const construction = artwork.querySelector('[data-part="construction-scene"]')!;
    const completed = artwork.querySelector('[data-part="completed-scene"]')!;
    expect(
      construction.compareDocumentPosition(completed)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    expect(artwork.querySelectorAll("[data-scene-plane]")).toHaveLength(0);
    for (const name of ["left-wall", "right-wall", "back-wall", "arch", "floor-grid", "sun"]) {
      expect(artwork.querySelector(`[data-scene-element="${name}"]`)).toBeTruthy();
    }
    expect(artwork.querySelectorAll('[data-scene-step]')).toHaveLength(0);
    expect(artwork.querySelector('[data-scene-focal="arched-portal"]')).toBeNull();
    expect(artwork.querySelector('[data-scene-light-path="portal-floor"]')).toBeNull();
    expect(artwork.querySelector('[data-part="scene-accent"]')).toBeTruthy();
    expect(artwork.querySelector('[data-part="scene-accent"]')?.getAttribute("fill")).toBe("none");
    expect(artwork.querySelector('[data-part="scene-scan-glow"]')).toBeNull();
    expect(artwork.querySelectorAll('[data-part="completed-scene"] path[fill]:not([fill="none"])')).toHaveLength(0);
    expect(artwork.querySelectorAll("radialGradient")).toHaveLength(0);
    expect(artwork.querySelector('[data-part="perspective-grid"]')).toBeNull();
    const core = artwork.querySelector('[data-part="scene-scan"] line');
    expect(core?.getAttribute("x1")).toBe("86");
    expect(core?.getAttribute("x2")).toBe("430");
    expect(artwork.querySelector('[data-part="doorway-scan"]')).toBeNull();
    expect(artwork.querySelector('[data-part="grid-emphasis"]')).toBeNull();
  });

  it("uses browser-supported direct clip geometry", () => {
    const { container } = render(<SceneDesignerAnimation motionState="idle" />);
    const clip = container.querySelector("clipPath")!;
    expect([...clip.children].map((child) => child.tagName.toLowerCase())).toEqual(["path", "path"]);
    for (const path of clip.children) {
      expect(path.getAttribute("transform")).toBe("translate(72 60) scale(1.3)");
    }
  });

  it("keeps the scan window stationary outside the moving scan group", () => {
    const { container } = render(<SceneDesignerAnimation motionState="working" />);
    const scan = container.querySelector('[data-part="scene-scan"]')!;
    const window = scan.parentElement!;
    expect(window.getAttribute("data-scene-scan-window")).toBe("true");
    expect(window.getAttribute("clip-path")).toMatch(/^url\(#.+\)$/);
    expect(window.hasAttribute("transform")).toBe(false);
    expect(window.hasAttribute("style")).toBe(false);
    expect(scan.hasAttribute("clip-path")).toBe(false);
  });

  it("replicates the atlas scene with open walls, a round arch, a perspective grid and eight sun rays", () => {
    const { container } = render(<SceneDesignerAnimation motionState="idle" />);
    for (const part of ["left-wall", "right-wall", "back-wall", "arch", "floor-grid", "sun"]) {
      expect(container.querySelectorAll(`[data-scene-element="${part}"]`)).toHaveLength(1);
    }
    expect(container.querySelectorAll('[data-scene-line="sun-ray"]')).toHaveLength(8);
    expect(container.querySelectorAll('[data-scene-line="grid-depth"]').length).toBeGreaterThanOrEqual(5);
    expect(container.querySelector('[data-scene-detail="courtyard-wall"]')).toBeNull();
    expect(container.querySelector('[data-scene-reference="atlas-row-2-col-1"]')?.getAttribute("transform"))
      .toBe("translate(72 60) scale(1.3)");
  });

  it("keeps the sun above the open rear wall and the floor lines spreading toward the foreground", () => {
    const { container } = render(<SceneDesignerAnimation motionState="idle" />);
    const sun = container.querySelector('[data-scene-line="sun-core"]');
    expect(sun?.getAttribute("cx")).toBe("115");
    expect(sun?.getAttribute("cy")).toBe("54");
    expect(sun?.getAttribute("r")).toBe("16");
    const crossLines = [...container.querySelectorAll('[data-scene-line="grid-cross"]')];
    const rows = crossLines.map((line) => Number(line.getAttribute("y1")));
    expect(rows).toEqual([192, 207, 227, 252]);
    const depths = [...container.querySelectorAll('[data-scene-line="grid-depth"]')];
    expect(Number(depths.at(-1)?.getAttribute("x2")) - Number(depths[0]?.getAttribute("x2")))
      .toBeGreaterThan(Number(depths.at(-1)?.getAttribute("x1")) - Number(depths[0]?.getAttribute("x1")));
    expect(container.querySelector('[data-scene-element="arch"] [stroke="#FFCA62"]')).toBeNull();
  });

  it("locks the reveal boundary and scan line through one top-to-bottom pass", () => {
    expect(SCENE_DESIGNER_MOTION_PROGRAM.working.map(({ part }) => part))
      .toEqual([
        "scene-reveal",
        "construction-hide",
        "scene-scan",
        "scene-accent",
      ]);
    expect(SCENE_DESIGNER_MOTION_PROGRAM.waiting).toEqual([]);
    expect(SCENE_DESIGNER_MOTION_PROGRAM.workingTransitionDurationMs).toBe(120);

    const reveal = trackFor("scene-reveal");
    const construction = trackFor("construction-hide");
    const scan = trackFor("scene-scan");
    for (const track of [reveal, construction, scan]) {
      expect(track.options).toEqual(expect.objectContaining({
        duration: 2_600,
        iterations: 1,
        fill: "forwards",
      }));
      expect(track.keyframes[1]?.easing)
        .toBe("cubic-bezier(0.77, 0, 0.175, 1)");
      expect(track.keyframes[2]?.easing)
        .toBe("cubic-bezier(0.23, 1, 0.32, 1)");
    }
    expect(reveal.keyframes.slice(0, 3).map(({ transform }) => transform))
      .toEqual(scan.keyframes.slice(0, 3).map(({ transform }) => transform));
    expect(construction.keyframes.slice(0, 3).map(({ transform }) => transform))
      .toEqual(scan.keyframes.slice(0, 3).map(({ transform }) => transform));
    expect(reveal.keyframes.at(-1)?.transform).toBe("translateY(392px)");
    expect(construction.keyframes.at(-1)?.transform).toBe("translateY(392px)");
    expect(scan.keyframes.at(-1)?.transform).toBe("translateY(368px)");

    const sceneAccent = trackFor("scene-accent");
    expect(sceneAccent.keyframes.map(({ opacity }) => opacity))
      .toEqual([0.78, 1, 0.78]);
    expect(sceneAccent.options).toEqual(expect.objectContaining({
      duration: 2_800,
      iterations: Infinity,
      easing: "cubic-bezier(0.77, 0, 0.175, 1)",
    }));
  });

  it("prepares the construction pose before a visible working frame", () => {
    const { container, rerender } = render(
      <SceneDesignerAnimation motionState="working" />,
    );

    const reveal = container.querySelector<SVGGraphicsElement>(
      '[data-part="scene-reveal"]',
    )!;
    const construction = container.querySelector<SVGGraphicsElement>(
      '[data-part="construction-hide"]',
    )!;
    const scan = container.querySelector<SVGGraphicsElement>(
      '[data-part="scene-scan"]',
    )!;

    expect(reveal.style.transform).toBe("translateY(0px)");
    expect(construction.style.transform).toBe("translateY(0px)");
    expect(scan.style.transform).toBe("translateY(0px)");
    expect(scan.style.opacity).toBe("1");

    rerender(<SceneDesignerAnimation motionState="idle" />);
    expect(reveal.style.transform).toBe("");
    expect(construction.style.transform).toBe("");
    expect(scan.style.opacity).toBe("");
  });

  it("ships a static poster from the shared completed artwork", () => {
    const expected = renderToStaticMarkup(
      <svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg">
        <SceneDesignerArtwork idPrefix="scene-poster" />
      </svg>,
    );
    const poster = readFileSync(
      "public/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg",
      "utf8",
    ).trim();
    expect(poster).toBe(expected);
    expect(poster).not.toMatch(/<script|<animate|<foreignObject/);
  });

  it("keeps the canonical completed pose for reduced motion", () => {
    stubReducedMotion(true);
    const { container } = render(<SceneDesignerAnimation motionState="working" />);

    expect(container.querySelector<SVGGraphicsElement>(
      '[data-part="scene-reveal"]',
    )?.style.transform).toBe("");
    expect(container.querySelector<SVGGraphicsElement>(
      '[data-part="construction-hide"]',
    )?.style.transform).toBe("");
    expect(container.querySelector<SVGGraphicsElement>(
      '[data-part="scene-scan"]',
    )?.style.opacity).toBe("");
  });

  it("connects the program to the shared motion lifecycle", () => {
    const { container } = render(<SceneDesignerAnimation motionState="working" />);
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: container.querySelector("svg") }),
      "working",
      SCENE_DESIGNER_MOTION_PROGRAM,
    );
  });
});
