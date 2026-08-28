import type { CanvasNodeV2 } from "../../../types-v2.ts";

export function creativeRoleDisplayName(role: CanvasNodeV2["creative_role"]): string {
  return role
    .split("_")
    .map((part) => part.toLowerCase() === "bgm"
      ? "BGM"
      : `${part.slice(0, 1).toUpperCase()}${part.slice(1).toLowerCase()}`)
    .join(" ");
}
