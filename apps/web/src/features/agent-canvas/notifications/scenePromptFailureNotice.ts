import type { UiMessageKey } from "../../../i18n/uiMessages.ts";
import type { CanvasNodeV2, NodeRuntimeV2 } from "../../../types-v2.ts";

export type ScenePromptFailureNode = Pick<CanvasNodeV2,
  | "workflow_id" | "node_id" | "creative_role" | "title" | "status"
  | "error" | "latest_attempt" | "prompt_preparation" | "generation_prompt" | "updated_at"
>;

export interface ScenePromptFailureNotice {
  key: string;
  nodeId: string;
  nodeTitle: string;
  reason: UiMessageKey;
  guidance: UiMessageKey;
}

const SCENE_PROHIBITION = "No people, product, prop interaction, narrative action, or text.";

export function scenePromptFailureNotice(
  node: ScenePromptFailureNode,
  runtime?: NodeRuntimeV2,
): ScenePromptFailureNotice | null {
  if (node.creative_role !== "scene") return null;
  const currentRuntime = runtime && Date.parse(runtime.updated_at) >= Date.parse(node.updated_at)
    ? runtime : null;
  const preparation = node.prompt_preparation;
  const status = currentRuntime?.visible_status ?? node.status;
  const error = status === "failed"
    ? currentRuntime?.error ?? node.error ?? node.latest_attempt?.error
    : status === "draft" && preparation?.status === "failed" ? preparation.error : null;
  if (error?.code !== "node_prompt_role_contract_invalid") return null;

  // This known system clause can itself trigger the backend's narrative check.
  // Describe it as a possible misclassification, not a verdict on user content.
  const prompt = node.generation_prompt ?? "";
  const policyStart = prompt.indexOf("\n\nDeterministic production policy:");
  const possiblePolicyRejection = error.violation_category === "narrative_progression"
    && policyStart >= 0 && prompt.slice(policyStart).includes(SCENE_PROHIBITION)
    && !/\b(?:narrative action|plot progression)\b/i.test(prompt.slice(0, policyStart));
  const attempt = status === "failed"
    ? currentRuntime?.execution_id ?? node.latest_attempt?.execution_id ?? node.updated_at
    : `${preparation?.operation_id}:${preparation?.attempt_no}`;
  return {
    key: `${node.workflow_id}:${node.node_id}:${attempt}:${error.code}`,
    nodeId: node.node_id,
    nodeTitle: node.title,
    reason: possiblePolicyRejection
      ? "The system may have mistaken a rule excluding narrative action for a request to add it. The scene image could not be generated."
      : "The scene prompt did not pass the environment-only check, so this scene image could not be generated.",
    guidance: possiblePolicyRejection
      ? "The system's handling of exclusion rules needs to be corrected before generating this scene again. Repeating the same request may fail again."
      : "Check that the scene description contains only the environment, spatial layout, lighting and materials before generating it again.",
  };
}
