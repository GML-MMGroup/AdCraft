import { memo, type ReactNode } from "react";

type WorkflowDebugPanelProps = {
  children: ReactNode;
};

export const WorkflowDebugPanel = memo(function WorkflowDebugPanel({ children }: WorkflowDebugPanelProps) {
  return <details className="advanced-node-details">{children}</details>;
});
