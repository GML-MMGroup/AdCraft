import { useEffect } from "react";
import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { AgentRoleAnimation } from "./agent-role-animation/AgentRoleAnimation.tsx";
import {
  agentRoleAnimationRegistry,
} from "./agent-role-animation/agentRoleAnimationRegistry.ts";
import { agentRoleBitmapManifest } from "./agent-role-animation/agentRoleBitmapManifest.ts";
import { prepareRoleVisual } from "./agent-role-animation/agentRoleVisualResource.ts";
import type { AgentRoleMotionState } from "./agent-role-animation/types.ts";

const preloadedIconLinks = new Set<string>();

export function agentCapabilityIconSource(capabilityId: AgentCapabilityIdV2): string | null {
  return capabilityId in agentRoleAnimationRegistry
    ? agentRoleBitmapManifest[capabilityId].source
    : null;
}

/** Start loading an icon as soon as its capability row is about to render. */
export function preloadAgentCapabilityIcon(capabilityId: AgentCapabilityIdV2): string | null {
  const source = agentCapabilityIconSource(capabilityId);
  if (!source || typeof Image === "undefined") return source;
  prepareRoleVisual(capabilityId, "bitmap");
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
    link.type = source.split("?")[0]?.endsWith(".svg") ? "image/svg+xml" : "image/png";
    link.setAttribute("fetchpriority", "high");
    link.href = source;
    document.head.appendChild(link);
  }
  preloadedIconLinks.add(source);
  return source;
}

export function AgentCapabilityIcon({
  capabilityId,
  motionState = "idle",
}: {
  capabilityId: AgentCapabilityIdV2;
  motionState?: AgentRoleMotionState;
}) {
  const source = agentCapabilityIconSource(capabilityId);
  useEffect(() => {
    preloadAgentCapabilityIcon(capabilityId);
  }, [capabilityId]);
  if (!source) return null;

  return (
    <span
      className="agent-chat__capability-icon"
      data-testid="agent-capability-icon"
      aria-hidden="true"
    >
      <AgentRoleAnimation capabilityId={capabilityId} motionState={motionState} />
    </span>
  );
}
