import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";

const AGENT_CAPABILITY_ICON_PATHS: Partial<Record<AgentCapabilityIdV2, string>> = {
  world_setting: "/imgs/agent-role-icons/world-setting.png",
  product_design: "/imgs/agent-role-icons/product-designer.png",
  prop_design: "/imgs/agent-role-icons/prop-designer.png",
  character_design: "/imgs/agent-role-icons/character-designer.png",
  scene_design: "/imgs/agent-role-icons/scene-designer.png",
  script_authoring: "/imgs/agent-role-icons/script-writer.png",
  storyboard_design: "/imgs/agent-role-icons/storyboard-artist.png",
  video_direction: "/imgs/agent-role-icons/video-director.png",
  bgm_direction: "/imgs/agent-role-icons/bgm-director.png",
  quick_media: "/imgs/agent-role-icons/quick-media.png",
};

const preloadedIconSources = new Set<string>();
const preloadedIconLinks = new Set<string>();

export function agentCapabilityIconSource(capabilityId: AgentCapabilityIdV2): string | null {
  return AGENT_CAPABILITY_ICON_PATHS[capabilityId] ?? null;
}

/** Start loading an icon as soon as its capability row is about to render. */
export function preloadAgentCapabilityIcon(capabilityId: AgentCapabilityIdV2): string | null {
  const source = agentCapabilityIconSource(capabilityId);
  if (!source || preloadedIconSources.has(source) || typeof Image === "undefined") return source;

  preloadedIconSources.add(source);
  const image = new Image();
  image.decoding = "async";
  image.src = source;
  return source;
}

/** Add a document preload hint for the capability that is currently entering the panel. */
export function preloadAgentCapabilityIconLink(capabilityId: AgentCapabilityIdV2): string | null {
  const source = agentCapabilityIconSource(capabilityId);
  if (!source || typeof document === "undefined" || preloadedIconLinks.has(source)) return source;

  const existing = [...document.head.querySelectorAll<HTMLLinkElement>(
    'link[rel="preload"][as="image"]',
  )].find((link) => link.getAttribute("href") === source);
  if (!existing) {
    const link = document.createElement("link");
    link.setAttribute("rel", "preload");
    link.setAttribute("as", "image");
    link.type = "image/png";
    link.setAttribute("fetchpriority", "high");
    link.href = source;
    document.head.appendChild(link);
  }
  preloadedIconLinks.add(source);
  return source;
}

export function AgentCapabilityIcon({
  capabilityId,
}: {
  capabilityId: AgentCapabilityIdV2;
}) {
  const source = preloadAgentCapabilityIcon(capabilityId);
  if (!source) return null;

  return (
    <img
      className="agent-chat__capability-icon"
      data-testid="agent-capability-icon"
      src={source}
      width={32}
      height={32}
      decoding="async"
      fetchPriority="high"
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
