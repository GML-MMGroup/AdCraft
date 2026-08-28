import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { AgentCapabilityIcon } from "./AgentCapabilityIcon.tsx";

const expectedIcons: Array<[AgentCapabilityIdV2, string]> = [
  ["world_setting", "/imgs/agent-role-icons/world-setting.png"],
  ["product_design", "/imgs/agent-role-icons/product-designer.png"],
  ["prop_design", "/imgs/agent-role-icons/prop-designer.png"],
  ["character_design", "/imgs/agent-role-icons/character-designer.png"],
  ["scene_design", "/imgs/agent-role-icons/scene-designer.png"],
  ["script_authoring", "/imgs/agent-role-icons/script-writer.png"],
  ["storyboard_design", "/imgs/agent-role-icons/storyboard-artist.png"],
  ["video_direction", "/imgs/agent-role-icons/video-director.png"],
  ["bgm_direction", "/imgs/agent-role-icons/bgm-director.png"],
  ["quick_media", "/imgs/agent-role-icons/quick-media.png"],
];

describe("AgentCapabilityIcon", () => {
  afterEach(() => cleanup());

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
  });
});
