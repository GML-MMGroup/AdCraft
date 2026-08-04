import type { ReactNode } from "react";

import {
  DocumentIcon,
  EditIcon,
  ImageIcon,
  MuteIcon,
  VideoIcon,
} from "../../../icons.tsx";
import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";
import { AGENT_CANVAS_NODE_LABELS } from "../model/nodeDefaults.ts";

function nodeIcon(type: CanvasNodeTypeV2): ReactNode {
  if (type === "text") return <EditIcon />;
  if (type === "script") return <DocumentIcon />;
  if (type === "image") return <ImageIcon />;
  if (type === "video") return <VideoIcon />;
  if (type === "audio") return <MuteIcon />;
  return <EditIcon />;
}

interface AgentCanvasNodePickerProps {
  className?: string;
  menuLabel: string;
  onSelect: (nodeType: CanvasNodeTypeV2) => void;
}

export function AgentCanvasNodePicker({
  className,
  menuLabel,
  onSelect,
}: AgentCanvasNodePickerProps) {
  return (
    <div className={className} role="menu" aria-label={menuLabel}>
      {(Object.keys(AGENT_CANVAS_NODE_LABELS) as CanvasNodeTypeV2[]).map((type) => (
        <button
          type="button"
          role="menuitem"
          key={type}
          aria-label={`Add ${AGENT_CANVAS_NODE_LABELS[type]} node`}
          onClick={() => onSelect(type)}
        >
          {nodeIcon(type)}
          <span>{AGENT_CANVAS_NODE_LABELS[type]}</span>
        </button>
      ))}
    </div>
  );
}
