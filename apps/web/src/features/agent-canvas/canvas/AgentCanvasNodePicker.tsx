import {
  AGENT_CANVAS_NODE_LABELS,
  AGENT_CANVAS_VISIBLE_NODE_TYPES,
  type AgentCanvasVisibleNodeTypeV2,
} from "../model/nodeDefaults.ts";
import { AgentCanvasNodeIcon } from "./AgentCanvasNodeIcon.tsx";

interface AgentCanvasNodePickerProps {
  className?: string;
  menuLabel: string;
  onSelect: (nodeType: AgentCanvasVisibleNodeTypeV2) => void;
}

export function AgentCanvasNodePicker({
  className,
  menuLabel,
  onSelect,
}: AgentCanvasNodePickerProps) {
  return (
    <div className={className} role="menu" aria-label={menuLabel}>
      {AGENT_CANVAS_VISIBLE_NODE_TYPES.map((type) => (
        <button
          type="button"
          role="menuitem"
          key={type}
          aria-label={`Add ${AGENT_CANVAS_NODE_LABELS[type]} node`}
          onClick={() => onSelect(type)}
        >
          <AgentCanvasNodeIcon nodeType={type} />
          <span>{AGENT_CANVAS_NODE_LABELS[type]}</span>
        </button>
      ))}
    </div>
  );
}
