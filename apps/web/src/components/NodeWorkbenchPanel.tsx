import { memo, type ReactNode } from "react";

type NodeWorkbenchPanelProps = {
  children: ReactNode;
};

export const NodeWorkbenchPanel = memo(function NodeWorkbenchPanel({ children }: NodeWorkbenchPanelProps) {
  return <section className="node-workbench-panel">{children}</section>;
});
