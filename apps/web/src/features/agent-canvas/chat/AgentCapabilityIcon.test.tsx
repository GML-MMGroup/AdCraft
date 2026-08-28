import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import {
  AgentCapabilityIcon,
  preloadAgentCapabilityIcon,
  preloadAgentCapabilityIconLink,
} from "./AgentCapabilityIcon.tsx";

const expectedIcons: Array<[AgentCapabilityIdV2, string]> = [
  ["world_setting", "/imgs/agent-role-icons/world-setting.png?v=2026-08-28"],
  ["product_design", "/imgs/agent-role-icons/product-designer.png?v=2026-08-28"],
  ["prop_design", "/imgs/agent-role-icons/prop-designer.png?v=2026-08-28"],
  ["character_design", "/imgs/agent-role-icons/character-designer.png?v=2026-08-28"],
  ["scene_design", "/imgs/agent-role-icons/scene-designer.png?v=2026-08-28"],
  ["script_authoring", "/imgs/agent-role-icons/script-writer.png?v=2026-08-28"],
  ["storyboard_design", "/imgs/agent-role-icons/storyboard-artist.png?v=2026-08-28"],
  ["video_direction", "/imgs/agent-role-icons/video-director.png?v=2026-08-28"],
  ["bgm_direction", "/imgs/agent-role-icons/bgm-director.png?v=2026-08-28"],
  ["quick_media", "/imgs/agent-role-icons/quick-media.png?v=2026-08-28"],
];

describe("AgentCapabilityIcon", () => {
  afterEach(() => cleanup());

  it("starts one image preload for a capability and reuses it", () => {
    const sources: string[] = [];
    const OriginalImage = window.Image;
    class MockImage {
      set src(value: string) {
        sources.push(value);
      }
    }
    Object.assign(window, { Image: MockImage });

    preloadAgentCapabilityIcon("world_setting");
    preloadAgentCapabilityIcon("world_setting");

    expect(sources).toEqual(["/imgs/agent-role-icons/world-setting.png?v=2026-08-28"]);
    Object.assign(window, { Image: OriginalImage });
  });

  it("maps every supported capability to a transparent public icon", () => {
    const { container } = render(
      <>
        {expectedIcons.map(([capabilityId]) => (
          <AgentCapabilityIcon key={capabilityId} capabilityId={capabilityId} />
        ))}
      </>,
    );

    expect([...container.querySelectorAll<HTMLImageElement>("img")].map((icon) => icon.src))
      .toEqual(expectedIcons.map(([, source]) => new URL(source, window.location.origin).href));
    expect([...container.querySelectorAll("img")].every((icon) => (
      icon.getAttribute("alt") === "" && icon.getAttribute("aria-hidden") === "true"
    ))).toBe(true);
    expect([...container.querySelectorAll<HTMLImageElement>("img")].every((icon) => (
      icon.getAttribute("width") === "32"
      && icon.getAttribute("height") === "32"
      && icon.getAttribute("decoding") === "async"
      && icon.getAttribute("fetchpriority") === "high"
    ))).toBe(true);
  });

  it("adds a deduplicated high-priority image preload link", () => {
    preloadAgentCapabilityIconLink("scene_design");
    preloadAgentCapabilityIconLink("scene_design");

    const links = [...document.head.querySelectorAll<HTMLLinkElement>(
      'link[rel="preload"][as="image"]',
    )].filter((link) => link.getAttribute("href") === "/imgs/agent-role-icons/scene-designer.png?v=2026-08-28");
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute("type")).toBe("image/png");
    expect(links[0]?.getAttribute("fetchpriority")).toBe("high");
  });
});
