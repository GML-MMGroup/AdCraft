import type { ReactNode } from "react";

import { CloseIcon, TrashIcon } from "../../../icons.tsx";
import type { CanvasNodeStatusV2, CanvasNodeTypeV2 } from "../../../types-v2.ts";

const STATUS_LABELS: Record<CanvasNodeStatusV2, string> = {
  draft: "Draft",
  working: "Working",
  ready: "Ready",
  failed: "Failed",
};

export function NodeWorkbenchShell({
  nodeType,
  title,
  status,
  pending,
  onDelete,
  onClose,
  children,
}: {
  nodeType: CanvasNodeTypeV2;
  title: string;
  status: CanvasNodeStatusV2;
  pending: boolean;
  onDelete: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <section
      className={`agent-node-workbench agent-node-workbench--${nodeType}`}
      aria-label={`${nodeType} node workbench`}
    >
      <header className="agent-node-workbench__header">
        <div>
          <span>{nodeType}</span>
          <strong>{title}</strong>
        </div>
        <div className="agent-node-workbench__header-actions">
          <span className={`agent-node-workbench__status is-${status}`}>{STATUS_LABELS[status]}</span>
          <button type="button" aria-label="Delete node" title="Delete node" disabled={pending} onClick={onDelete}>
            <TrashIcon />
          </button>
          <button type="button" aria-label="Close node workbench" title="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
      </header>
      {children}
    </section>
  );
}
