import type { WorkflowNode } from "../../../types";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";

export function canShowLocalRevisionActions(node?: WorkflowNode | null) {
  if (!node) return false;
  const nodeType = getWorkflowNodeType(node).toLowerCase();
  if (nodeType === "final-composition") return false;
  return ["character-generation", "scene-generation", "storyboard", "storyboard-video-generation", "bgm"].includes(nodeType);
}
