import type { ComponentType } from "react";

import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import type { AgentRoleMotionState } from "./types.ts";
import BgmDirectorAnimation from "./roles/BgmDirectorAnimation.tsx";
import CharacterDesignerAnimation from "./roles/CharacterDesignerAnimation.tsx";
import ProductDesignerAnimation from "./roles/ProductDesignerAnimation.tsx";
import PropDesignerAnimation from "./roles/PropDesignerAnimation.tsx";
import QuickMediaAnimation from "./roles/QuickMediaAnimation.tsx";
import SceneDesignerAnimation from "./roles/SceneDesignerAnimation.tsx";
import ScriptWriterAnimation from "./roles/ScriptWriterAnimation.tsx";
import StoryboardArtistAnimation from "./roles/StoryboardArtistAnimation.tsx";
import VideoDirectorAnimation from "./roles/VideoDirectorAnimation.tsx";
import WorldSettingAnimation from "./roles/WorldSettingAnimation.tsx";

const AGENT_ICON_ASSET_VERSION = "2026-08-28";

export type AgentRoleArtworkComponent = ComponentType<{
  motionState: AgentRoleMotionState;
}>;

interface AgentRoleAnimationRegistryEntry {
  staticSource: string;
  load: () => Promise<AgentRoleArtworkComponent>;
  retryLoad: () => Promise<AgentRoleArtworkComponent>;
}

export const agentRoleAnimationRegistry = {
  world_setting: {
    staticSource: `/imgs/agent-role-icons/world-setting.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => WorldSettingAnimation,
    retryLoad: async () => WorldSettingAnimation,
  },
  product_design: {
    staticSource: `/imgs/agent-role-icons/product-designer.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => ProductDesignerAnimation,
    retryLoad: async () => ProductDesignerAnimation,
  },
  prop_design: {
    staticSource: `/imgs/agent-role-icons/prop-designer.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => PropDesignerAnimation,
    retryLoad: async () => PropDesignerAnimation,
  },
  character_design: {
    staticSource: "/imgs/agent-role-icons/character-designer-20260906-line-art.svg",
    load: async () => CharacterDesignerAnimation,
    retryLoad: async () => CharacterDesignerAnimation,
  },
  scene_design: {
    staticSource: "/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg",
    load: async () => SceneDesignerAnimation,
    retryLoad: async () => SceneDesignerAnimation,
  },
  script_authoring: {
    staticSource: `/imgs/agent-role-icons/script-writer.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => ScriptWriterAnimation,
    retryLoad: async () => ScriptWriterAnimation,
  },
  storyboard_design: {
    staticSource: `/imgs/agent-role-icons/storyboard-artist.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => StoryboardArtistAnimation,
    retryLoad: async () => StoryboardArtistAnimation,
  },
  video_direction: {
    staticSource: `/imgs/agent-role-icons/video-director.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => VideoDirectorAnimation,
    retryLoad: async () => VideoDirectorAnimation,
  },
  bgm_direction: {
    staticSource: `/imgs/agent-role-icons/bgm-director.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => BgmDirectorAnimation,
    retryLoad: async () => BgmDirectorAnimation,
  },
  quick_media: {
    staticSource: `/imgs/agent-role-icons/quick-media.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: async () => QuickMediaAnimation,
    retryLoad: async () => QuickMediaAnimation,
  },
} satisfies Record<AgentCapabilityIdV2, AgentRoleAnimationRegistryEntry>;

const retriedCapabilities = new Set<AgentCapabilityIdV2>();

const animationPromiseCache = new Map<
  AgentCapabilityIdV2,
  Promise<AgentRoleArtworkComponent>
>();

export function agentRoleStaticIconSource(capabilityId: AgentCapabilityIdV2): string {
  return agentRoleAnimationRegistry[capabilityId].staticSource;
}

export function preloadAgentRoleAnimation(
  capabilityId: AgentCapabilityIdV2,
): Promise<AgentRoleArtworkComponent> {
  const cached = animationPromiseCache.get(capabilityId);
  if (cached) return cached;

  const promise = Promise.resolve().then(
    () => retriedCapabilities.has(capabilityId)
      ? agentRoleAnimationRegistry[capabilityId].retryLoad()
      : agentRoleAnimationRegistry[capabilityId].load(),
  );
  animationPromiseCache.set(capabilityId, promise);
  return promise;
}

/** Explicit user retry only; ordinary renders continue sharing a rejected promise. */
export function retryAgentRoleAnimation(capabilityId: AgentCapabilityIdV2): void {
  if (retriedCapabilities.has(capabilityId)) return;
  retriedCapabilities.add(capabilityId);
  animationPromiseCache.delete(capabilityId);
}

export function canRetryAgentRoleAnimation(capabilityId: AgentCapabilityIdV2): boolean {
  return !retriedCapabilities.has(capabilityId);
}

/** Test isolation only. Production failures remain cached until one explicit retry. */
export function resetAgentRoleAnimationCacheForTests(): void {
  animationPromiseCache.clear();
  retriedCapabilities.clear();
}
