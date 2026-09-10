import type { ComponentType } from "react";

import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import type { AgentRoleMotionState } from "./types.ts";

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
    load: () => import("./roles/WorldSettingAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/WorldSettingAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  product_design: {
    staticSource: `/imgs/agent-role-icons/product-designer.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/ProductDesignerAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/ProductDesignerAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  prop_design: {
    staticSource: `/imgs/agent-role-icons/prop-designer.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/PropDesignerAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/PropDesignerAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  character_design: {
    staticSource: "/imgs/agent-role-icons/character-designer-20260906-line-art.svg",
    load: () => import("./roles/CharacterDesignerAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/CharacterDesignerAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  scene_design: {
    staticSource: "/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg",
    load: () => import("./roles/SceneDesignerAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/SceneDesignerAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  script_authoring: {
    staticSource: `/imgs/agent-role-icons/script-writer.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/ScriptWriterAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/ScriptWriterAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  storyboard_design: {
    staticSource: `/imgs/agent-role-icons/storyboard-artist.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/StoryboardArtistAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/StoryboardArtistAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  video_direction: {
    staticSource: `/imgs/agent-role-icons/video-director.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/VideoDirectorAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/VideoDirectorAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  bgm_direction: {
    staticSource: `/imgs/agent-role-icons/bgm-director.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/BgmDirectorAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/BgmDirectorAnimation.tsx?agent-role-retry").then((module) => module.default()),
  },
  quick_media: {
    staticSource: `/imgs/agent-role-icons/quick-media.png?v=${AGENT_ICON_ASSET_VERSION}`,
    load: () => import("./roles/QuickMediaAnimation.tsx").then((module) => module.default),
    retryLoad: () => import("./roles/QuickMediaAnimation.tsx?agent-role-retry").then((module) => module.default()),
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
