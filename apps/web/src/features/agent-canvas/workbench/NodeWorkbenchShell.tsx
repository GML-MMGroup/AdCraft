import { useState, type ReactNode } from "react";
import { NodeWorkbenchFeedbackContext } from "./nodeWorkbenchFeedbackContext.ts";

import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function NodeWorkbenchShell({
  nodeType,
  children,
}: {
  nodeType: CanvasNodeTypeV2;
  children: ReactNode;
}) {
  const [feedbackTarget, setFeedbackTarget] = useState<HTMLDivElement | null>(null);
  const t = useTranslation("en-US");
  return (
    <section
      className={`agent-node-workbench agent-node-workbench--${nodeType}`}
      aria-label={t("{type} node workbench", { type: nodeType })}
    >
      <NodeWorkbenchFeedbackContext.Provider value={feedbackTarget}>
        {children}
      </NodeWorkbenchFeedbackContext.Provider>
      <div className="agent-node-workbench__feedback nodrag nopan nowheel" ref={setFeedbackTarget} />
    </section>
  );
}
