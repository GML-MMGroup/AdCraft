import { translateUi, type MessageValues, type UiMessageKey } from "../../../i18n/uiMessages.ts";
import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { canvasNodeIdentity } from "./canvasNodeIdentity.ts";
import { projectCharacterNodePresentation } from "./characterNodePresentation.ts";
import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";

type Translate = (key: UiMessageKey, values?: MessageValues) => string;
const english: Translate = (key, values) => translateUi("en-US", key, values);

/** Labels use persisted creative identity, never canvas position, array order, or run state. */
export function canvasNodeDisplayName(node: CanvasNodeV2, t: Translate = english): string {
  const number = canvasNodeIdentity(node)?.number ?? null;
  const character = projectCharacterNodePresentation(node);
  if (character) {
    if (number !== null) {
      const key = character.phase === "main" ? "Character {number} · Main"
        : character.phase === "turnaround" ? "Character {number} · Turnaround"
          : "Character {number}";
      return t(key, { number });
    }
    return t(character.phaseLabel);
  }

  if (node.creative_role === "storyboard_sequence" || node.creative_role === "storyboard_video") {
    if (number !== null) {
      return t(node.creative_role === "storyboard_sequence" ? "Storyboard {number}" : "Storyboard Video {number}", { number });
    }
    return t(node.creative_role === "storyboard_sequence" ? "Storyboard Sequence" : "Storyboard Video");
  }

  return t(creativeRoleDisplayName(node.creative_role));
}
