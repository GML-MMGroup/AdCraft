import { WorkflowPageView } from "./WorkflowPageView";
import { useWorkflowPageModel } from "./page/useWorkflowPageModel";

export function WorkflowPage() {
  const page = useWorkflowPageModel();
  return <WorkflowPageView model={page.model} actions={page.actions} />;
}
