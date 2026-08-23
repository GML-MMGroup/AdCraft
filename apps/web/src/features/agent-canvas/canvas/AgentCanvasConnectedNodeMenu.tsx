import { useState } from "react";
import type {
  CanvasBindingInputRoleV2,
  CanvasConnectionPolicyV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import {
  AGENT_CANVAS_NODE_LABELS,
  isAgentCanvasVisibleNodeType,
  type AgentCanvasVisibleNodeTypeV2,
} from "../model/nodeDefaults.ts";
import { AgentCanvasNodeIcon } from "./AgentCanvasNodeIcon.tsx";
import {
  compatibleConnectedNodeTypes,
  connectionRuleForPair,
} from "./connectionPolicy.ts";
import "./AgentCanvasConnectedNodeMenu.css";

interface AgentCanvasConnectedNodeMenuProps {
  anchorNode: CanvasNodeV2;
  direction: "upstream" | "downstream";
  point: { x: number; y: number };
  policy: CanvasConnectionPolicyV2;
  onSelect: (nodeType: AgentCanvasVisibleNodeTypeV2, inputRole: CanvasBindingInputRoleV2) => void;
  onClose: () => void;
}

export function AgentCanvasConnectedNodeMenu({
  anchorNode,
  direction,
  point,
  policy,
  onSelect,
  onClose,
}: AgentCanvasConnectedNodeMenuProps) {
  const [selectedRoles, setSelectedRoles] = useState<
    Partial<Record<CanvasNodeTypeV2, CanvasBindingInputRoleV2>>
  >({});
  const compatibleTypes = compatibleConnectedNodeTypes(
    policy,
    anchorNode.node_type,
    direction,
  ).filter(isAgentCanvasVisibleNodeType);

  return (
    <>
      <button
        type="button"
        className="agent-canvas-connected-menu__backdrop"
        aria-label="Close connected node menu"
        onClick={onClose}
      />
      <div
        className="agent-canvas-connected-menu"
        role="menu"
        aria-label={`Add ${direction} node`}
        style={{
          left: `min(${Math.max(12, point.x)}px, calc(100vw - 228px))`,
          top: `min(${Math.max(12, point.y)}px, calc(100vh - 320px))`,
        }}
      >
        <span className="agent-canvas-connected-menu__eyebrow">
          {direction === "upstream" ? "Add input" : "Add output"}
        </span>
        {compatibleTypes.length ? compatibleTypes.map((nodeType) => {
          const sourceType = direction === "downstream" ? anchorNode.node_type : nodeType;
          const targetType = direction === "downstream" ? nodeType : anchorNode.node_type;
          const rule = connectionRuleForPair(policy, sourceType, targetType);
          if (!rule) return null;
          const selectedRole = selectedRoles[nodeType] ?? rule.default_role;
          return (
            <div className="agent-canvas-connected-menu__option" key={nodeType}>
              <button
                type="button"
                role="menuitem"
                aria-label={`Create connected ${AGENT_CANVAS_NODE_LABELS[nodeType]} node`}
                onClick={() => onSelect(nodeType, selectedRole)}
              >
                <AgentCanvasNodeIcon nodeType={nodeType} />
                <span>
                  <strong>{AGENT_CANVAS_NODE_LABELS[nodeType]}</strong>
                  <small>{selectedRole.replaceAll("_", " ")}</small>
                </span>
              </button>
              {rule.roles.length > 1 ? (
                <select
                  aria-label={`Input role for ${AGENT_CANVAS_NODE_LABELS[nodeType]}`}
                  value={selectedRole}
                  onChange={(event) => setSelectedRoles((current) => ({
                    ...current,
                    [nodeType]: event.currentTarget.value as CanvasBindingInputRoleV2,
                  }))}
                >
                  {rule.roles.map((role) => (
                    <option value={role} key={role}>{role.replaceAll("_", " ")}</option>
                  ))}
                </select>
              ) : null}
            </div>
          );
        }) : (
          <p>No compatible {direction} node types.</p>
        )}
      </div>
    </>
  );
}
