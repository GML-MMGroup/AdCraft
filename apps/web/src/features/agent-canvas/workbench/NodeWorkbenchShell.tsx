import type { ReactNode } from "react";

import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";

export function NodeWorkbenchShell({
  nodeType,
  children,
}: {
  nodeType: CanvasNodeTypeV2;
  children: ReactNode;
}) {
  return (
    <section
      className={`agent-node-workbench agent-node-workbench--${nodeType}`}
      aria-label={`${nodeType} node workbench`}
    >
      {children}
    </section>
  );
}
