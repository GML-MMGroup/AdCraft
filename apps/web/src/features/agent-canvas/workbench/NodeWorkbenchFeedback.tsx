import { useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { NodeWorkbenchFeedbackContext } from "./nodeWorkbenchFeedbackContext.ts";

export function NodeWorkbenchFeedback({ children }: { children: ReactNode }) {
  const target = useContext(NodeWorkbenchFeedbackContext);
  if (target === undefined) return children;
  return target ? createPortal(children, target) : null;
}

export function NodeWorkbenchFieldError({ children }: { children: ReactNode }) {
  return (
    <NodeWorkbenchFeedback>
      <p className="agent-node-workbench__field-error" role="alert">{children}</p>
    </NodeWorkbenchFeedback>
  );
}
