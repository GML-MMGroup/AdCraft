import {
  WorkflowDraggablePanel,
  type DraggablePanelKey,
  type PanelOffset,
} from "../../../components/WorkflowDraggablePanel.tsx";
import { CloseIcon } from "../../../icons.tsx";
import { lazy, Suspense } from "react";

const V2FinalCompositionEditor = lazy(() => import("./V2FinalCompositionEditor.tsx").then((module) => ({
  default: module.V2FinalCompositionEditor,
})));

export type V2FinalCompositionPanelProps = {
  workflowId: string;
  offset: PanelOffset;
  onOffsetCommit: (panelKey: DraggablePanelKey, offset: PanelOffset) => void;
  onClose: () => void;
  onWorkflowRefresh: (workflowId: string) => Promise<unknown> | unknown;
};

export function V2FinalCompositionPanel({
  workflowId,
  offset,
  onOffsetCommit,
  onClose,
  onWorkflowRefresh,
}: V2FinalCompositionPanelProps) {
  return (
    <WorkflowDraggablePanel
      as="aside"
      panelKey="detail"
      offset={offset}
      className="v2-final-composition-panel nodrag"
      headingClassName="v2-final-composition-panel-heading"
      heading={
        <>
          <div className="v2-final-composition-panel-title">
            <strong>Final Composition Editor</strong>
            <span className="panel-drag-grip" aria-hidden="true">::</span>
          </div>
          <button
            type="button"
            className="v2-final-composition-panel-close"
            aria-label="Close Final Composition editor"
            title="Close Final Composition editor"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onClose();
            }}
          >
            <CloseIcon />
          </button>
        </>
      }
      onOffsetCommit={onOffsetCommit}
    >
      <div className="v2-final-composition-panel-body">
        <Suspense fallback={<V2FinalCompositionEditorLoading />}>
          <V2FinalCompositionEditor
            workflowId={workflowId}
            active
            onWorkflowRefresh={onWorkflowRefresh}
          />
        </Suspense>
      </div>
    </WorkflowDraggablePanel>
  );
}

function V2FinalCompositionEditorLoading() {
  return <p className="v2-composition-editor-loading">Loading Final Composition editor...</p>;
}
