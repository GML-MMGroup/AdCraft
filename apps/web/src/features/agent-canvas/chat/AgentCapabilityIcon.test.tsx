import { cleanup, render } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./agent-role-animation/AgentRoleAnimation.tsx", () => ({
  AgentRoleAnimation: ({
    capabilityId,
    motionState,
  }: {
    capabilityId: AgentCapabilityIdV2;
    motionState: string;
  }) => (
    <span
      data-testid="agent-role-animation-double"
      data-capability-id={capabilityId}
      data-motion-state={motionState}
    />
  ),
}));

import { agentRoleBitmapManifest } from "./agent-role-animation/agentRoleBitmapManifest.ts";
import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import {
  AgentCapabilityIcon,
  agentCapabilityIconSource,
  preloadAgentCapabilityIcon,
  preloadAgentCapabilityIconLink,
} from "./AgentCapabilityIcon.tsx";

const expectedIcons = Object.entries(agentRoleBitmapManifest).map(([role, asset]) => [role, asset.source] as [AgentCapabilityIdV2, string]);

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

    expect(sources).toEqual([agentRoleBitmapManifest.world_setting.source, agentRoleBitmapManifest.world_setting.fallback]);
    Object.assign(window, { Image: OriginalImage });
  });

  it("keeps render free of image I/O and preloads after client effects", () => {
    const sources: string[] = [];
    const OriginalImage = window.Image;
    class MockImage {
      set src(value: string) {
        sources.push(value);
      }
    }
    Object.assign(window, { Image: MockImage });

    renderToString(<AgentCapabilityIcon capabilityId="video_direction" />);
    expect(sources).toEqual([]);

    render(<AgentCapabilityIcon capabilityId="video_direction" />);
    expect(sources).toEqual([
      agentRoleBitmapManifest.video_direction.source, agentRoleBitmapManifest.video_direction.fallback,
    ]);
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

    expect(expectedIcons.map(([capabilityId]) => agentCapabilityIconSource(capabilityId)))
      .toEqual(expectedIcons.map(([, source]) => source));
    expect(container.querySelectorAll('[data-testid="agent-capability-icon"]'))
      .toHaveLength(expectedIcons.length);
    expect([...container.querySelectorAll<HTMLElement>(
      '[data-testid="agent-role-animation-double"]',
    )].map((animation) => [
      animation.dataset.capabilityId,
      animation.dataset.motionState,
    ])).toEqual(expectedIcons.map(([capabilityId]) => [capabilityId, "idle"]));
  });

  it("forwards an explicit motion state to the role animation host", () => {
    render(<AgentCapabilityIcon capabilityId="scene_design" motionState="working" />);

    const frame = document.querySelector<HTMLElement>('[data-testid="agent-capability-icon"]');
    const animation = frame?.querySelector<HTMLElement>(
      '[data-testid="agent-role-animation-double"]',
    );
    expect(frame?.classList.contains("agent-chat__capability-icon")).toBe(true);
    expect(animation?.dataset.capabilityId).toBe("scene_design");
    expect(animation?.dataset.motionState).toBe("working");
  });

  it("adds a deduplicated high-priority image preload link", () => {
    preloadAgentCapabilityIconLink("scene_design");
    preloadAgentCapabilityIconLink("scene_design");

    const links = [...document.head.querySelectorAll<HTMLLinkElement>(
      'link[rel="preload"][as="image"]',
    )].filter((link) => link.getAttribute("href") === agentRoleBitmapManifest.scene_design.source);
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute("type")).toBe("image/png");
    expect(links[0]?.getAttribute("fetchpriority")).toBe("high");
  });
});
