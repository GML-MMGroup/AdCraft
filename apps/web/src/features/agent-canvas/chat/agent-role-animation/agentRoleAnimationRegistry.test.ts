import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import {
  agentRoleAnimationRegistry,
  agentRoleStaticIconSource,
  preloadAgentRoleAnimation,
  retryAgentRoleAnimation,
  resetAgentRoleAnimationCacheForTests,
} from "./agentRoleAnimationRegistry.ts";

const EXPECTED_ROLE_SOURCES: Array<[AgentCapabilityIdV2, string]> = [
  ["world_setting", "/imgs/agent-role-icons/world-setting.png?v=2026-08-28"],
  ["product_design", "/imgs/agent-role-icons/product-designer.png?v=2026-08-28"],
  ["prop_design", "/imgs/agent-role-icons/prop-designer.png?v=2026-08-28"],
  ["character_design", "/imgs/agent-role-icons/character-designer-20260906-line-art.svg"],
  ["scene_design", "/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg"],
  ["script_authoring", "/imgs/agent-role-icons/script-writer.png?v=2026-08-28"],
  ["storyboard_design", "/imgs/agent-role-icons/storyboard-artist.png?v=2026-08-28"],
  ["video_direction", "/imgs/agent-role-icons/video-director.png?v=2026-08-28"],
  ["bgm_direction", "/imgs/agent-role-icons/bgm-director.png?v=2026-08-28"],
  ["quick_media", "/imgs/agent-role-icons/quick-media.png?v=2026-08-28"],
];

describe("agentRoleAnimationRegistry", () => {
  afterEach(() => {
    resetAgentRoleAnimationCacheForTests();
    vi.restoreAllMocks();
  });

  it("covers exactly the ten capabilities with versioned static fallbacks", () => {
    expect(Object.keys(agentRoleAnimationRegistry)).toEqual(
      EXPECTED_ROLE_SOURCES.map(([capabilityId]) => capabilityId),
    );
    expect(EXPECTED_ROLE_SOURCES.map(([capabilityId]) => (
      agentRoleStaticIconSource(capabilityId)
    ))).toEqual(EXPECTED_ROLE_SOURCES.map(([, source]) => source));
  });

  it("starts one lazy load per capability and returns the cached promise", async () => {
    const SceneArtwork = () => null;
    const ProductArtwork = () => null;
    const loadScene = vi.spyOn(agentRoleAnimationRegistry.scene_design, "load")
      .mockResolvedValue(SceneArtwork);
    const loadProduct = vi.spyOn(agentRoleAnimationRegistry.product_design, "load")
      .mockResolvedValue(ProductArtwork);

    const firstLoad = preloadAgentRoleAnimation("scene_design");
    const secondLoad = preloadAgentRoleAnimation("scene_design");
    const productLoad = preloadAgentRoleAnimation("product_design");

    expect(secondLoad).toBe(firstLoad);
    expect(productLoad).not.toBe(firstLoad);
    await expect(firstLoad).resolves.toBe(SceneArtwork);
    await expect(productLoad).resolves.toBe(ProductArtwork);
    expect(loadScene).toHaveBeenCalledTimes(1);
    expect(loadProduct).toHaveBeenCalledTimes(1);
  });

  it("keeps a rejected import cached for the session", async () => {
    const failure = new Error("role chunk unavailable");
    const load = vi.spyOn(agentRoleAnimationRegistry.scene_design, "load")
      .mockRejectedValue(failure);

    const firstLoad = preloadAgentRoleAnimation("scene_design");
    await expect(firstLoad).rejects.toBe(failure);

    const secondLoad = preloadAgentRoleAnimation("scene_design");
    await expect(secondLoad).rejects.toBe(failure);
    expect(secondLoad).toBe(firstLoad);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("explicitly retries a failed module instead of caching the rejection forever", async () => {
    const Artwork = () => null;
    const load = vi.spyOn(agentRoleAnimationRegistry.scene_design, "load")
      .mockRejectedValueOnce(new Error("offline"));
    const retryLoad = vi.spyOn(agentRoleAnimationRegistry.scene_design, "retryLoad").mockResolvedValue(Artwork);
    await expect(preloadAgentRoleAnimation("scene_design")).rejects.toThrow("offline");
    retryAgentRoleAnimation("scene_design");
    await expect(preloadAgentRoleAnimation("scene_design")).resolves.toBe(Artwork);
    expect(load).toHaveBeenCalledTimes(1);
    expect(retryLoad).toHaveBeenCalledTimes(1);
    retryAgentRoleAnimation("scene_design");
    await expect(preloadAgentRoleAnimation("scene_design")).resolves.toBe(Artwork);
    expect(retryLoad).toHaveBeenCalledTimes(1);
  });
});
