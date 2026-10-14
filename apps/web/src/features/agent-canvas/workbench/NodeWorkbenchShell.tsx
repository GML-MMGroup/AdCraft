import type { ReactNode } from "react";

import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function NodeWorkbenchShell({
  nodeType,
  children,
}: {
  nodeType: CanvasNodeTypeV2;
  children: ReactNode;
}) {
  const t = useTranslation("en-US");
  return (
    <section
      className={`agent-node-workbench agent-node-workbench--${nodeType}`}
      aria-label={t("{type} node workbench", { type: nodeType })}
    >
      {children}
    </section>
  );
}
