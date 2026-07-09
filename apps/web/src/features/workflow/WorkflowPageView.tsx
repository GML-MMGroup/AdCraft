import type { WorkflowPageViewProps } from "./page/workflowPageTypes";

export function WorkflowPageView({ model }: WorkflowPageViewProps) {
  return (
    <>
      {model.copilot}
      {model.canvas}
      {model.panels}
      {model.modals}
    </>
  );
}
