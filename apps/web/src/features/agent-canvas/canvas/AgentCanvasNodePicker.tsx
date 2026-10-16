import {
  AGENT_CANVAS_NODE_LABELS,
  AGENT_CANVAS_VISIBLE_NODE_TYPES,
  type AgentCanvasVisibleNodeTypeV2,
} from "../model/nodeDefaults.ts";
import { AgentCanvasNodeIcon } from "./AgentCanvasNodeIcon.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";

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
  const t = useTranslation("en-US");
  return (
    <div className={className} role="menu" aria-label={menuLabel}>
      {AGENT_CANVAS_VISIBLE_NODE_TYPES.map((type) => (
        <button
          type="button"
          role="menuitem"
          key={type}
          aria-label={t("Add {type} node", { type: AGENT_CANVAS_NODE_LABELS[type] })}
          onClick={() => onSelect(type)}
        >
          <AgentCanvasNodeIcon nodeType={type} />
          <span>{t(AGENT_CANVAS_NODE_LABELS[type] as "Text" | "Script" | "Image" | "Video" | "Audio" | "Editing")}</span>
        </button>
      ))}
    </div>
  );
}
