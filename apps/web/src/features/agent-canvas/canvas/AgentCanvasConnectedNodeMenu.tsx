import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
import { useTranslation } from "../../../i18n/useTranslation.ts";

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
  const t = useTranslation("en-US");
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const focusTarget = menuRef.current?.querySelector<HTMLButtonElement>("[role=menuitem]") ?? menuRef.current;
    focusTarget?.focus({ preventScroll: true });
    const dismiss = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", dismiss, true);
    return () => document.removeEventListener("keydown", dismiss, true);
  }, [onClose]);
  const [selectedRoles, setSelectedRoles] = useState<
    Partial<Record<CanvasNodeTypeV2, CanvasBindingInputRoleV2>>
  >({});
  const compatibleTypes = compatibleConnectedNodeTypes(
    policy,
    anchorNode.node_type,
    direction,
  ).filter(isAgentCanvasVisibleNodeType);

  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const bounds = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(12, Math.min(point.x, window.innerWidth - bounds.width - 12))}px`;
    menu.style.top = `${Math.max(12, Math.min(point.y, window.innerHeight - bounds.height - 12))}px`;
  }, [point.x, point.y, compatibleTypes.length]);

  return (
    <>
      <button
        type="button"
        className="agent-canvas-connected-menu__backdrop"
        aria-label={t("Close connected node menu")}
        onClick={onClose}
      />
      <div
        ref={menuRef}
        className="agent-canvas-connected-menu"
        role="menu"
        tabIndex={-1}
        aria-label={t("Add {direction} node", { direction })}
        style={{
          left: point.x,
          top: point.y,
        }}
      >
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
                aria-label={t("Create connected {type} node", { type: AGENT_CANVAS_NODE_LABELS[nodeType] })}
                onClick={() => onSelect(nodeType, selectedRole)}
              >
                <AgentCanvasNodeIcon nodeType={nodeType} />
                <span>
                  <strong>{AGENT_CANVAS_NODE_LABELS[nodeType]}</strong>
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
          <p>{t("No compatible {direction} node types.", { direction })}</p>
        )}
      </div>
    </>
  );
}
