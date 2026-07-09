import { memo, type ReactNode } from "react";

type WorkflowCopilotPanelProps = {
  collapsed: boolean;
  children: ReactNode;
};

export const WorkflowCopilotPanel = memo(function WorkflowCopilotPanel({ collapsed, children }: WorkflowCopilotPanelProps) {
  return (
    <aside className={`copilot-panel ${collapsed ? "is-collapsed" : ""}`} id="copilotPanel">
      {children}
    </aside>
  );
});
