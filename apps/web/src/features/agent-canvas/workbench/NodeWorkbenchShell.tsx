import type { ReactNode } from "react";

import { CloseIcon, TrashIcon } from "../../../icons.tsx";
import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";

export function NodeWorkbenchShell({
  nodeType,
  pending,
  onDelete,
  onClose,
  children,
}: {
  nodeType: CanvasNodeTypeV2;
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
      <div className="agent-node-workbench__quick-actions">
        <button type="button" aria-label="Delete node" title="Delete node" disabled={pending} onClick={onDelete}>
          <TrashIcon />
        </button>
        <button type="button" aria-label="Close node workbench" title="Close" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      {children}
    </section>
  );
}
