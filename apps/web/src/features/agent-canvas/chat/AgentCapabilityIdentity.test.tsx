import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";

const expectedRoleClasses: Array<[AgentCapabilityIdV2, string]> = [
  ["world_setting", "is-role-world-setting"],
  ["product_design", "is-role-product-design"],
  ["prop_design", "is-role-prop-design"],
  ["character_design", "is-role-character-design"],
  ["scene_design", "is-role-scene-design"],
  ["script_authoring", "is-role-script-authoring"],
  ["storyboard_design", "is-role-storyboard-design"],
  ["video_direction", "is-role-video-direction"],
  ["bgm_direction", "is-role-bgm-direction"],
  ["quick_media", "is-role-quick-media"],
];

describe("AgentCapabilityIdentity", () => {
  afterEach(() => cleanup());

  it("assigns a stable semantic accent class to every capability", () => {
    const { container } = render(
      <>
        {expectedRoleClasses.map(([capabilityId]) => (
          <AgentCapabilityIdentity
            key={capabilityId}
            capabilityId={capabilityId}
            displayName={capabilityId}
            detail="Working"
          />
        ))}
      </>,
    );

    const identities = [...container.querySelectorAll(".agent-chat__capability-identity")];
    expect(identities).toHaveLength(expectedRoleClasses.length);
    expectedRoleClasses.forEach(([, className], index) => {
      expect(identities[index]?.classList.contains(className)).toBe(true);
    });
  });
});
