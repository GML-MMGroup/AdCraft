import type {
  CanvasConnectionPolicyV2,
  CanvasConnectionRoleRuleV2,
  CanvasNodeTypeV2,
} from "../../../types-v2.ts";

export function connectionRuleForPair(
  policy: CanvasConnectionPolicyV2,
  sourceType: CanvasNodeTypeV2,
  targetType: CanvasNodeTypeV2,
): CanvasConnectionRoleRuleV2 | null {
  return policy.input_roles.find((rule) => (
    rule.source_node_type === sourceType
    && rule.target_node_type === targetType
  )) ?? null;
}

export function compatibleConnectedNodeTypes(
  policy: CanvasConnectionPolicyV2,
  anchorType: CanvasNodeTypeV2,
  direction: "upstream" | "downstream",
): CanvasNodeTypeV2[] {
  const matches = policy.input_roles.flatMap((rule) => {
    if (direction === "downstream" && rule.source_node_type === anchorType) {
      return [rule.target_node_type];
    }
    if (direction === "upstream" && rule.target_node_type === anchorType) {
      return [rule.source_node_type];
    }
    return [];
  });
  return Array.from(new Set(matches));
}
