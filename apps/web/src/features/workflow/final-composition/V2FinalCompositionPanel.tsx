import {
  WorkflowDraggablePanel,
  type DraggablePanelKey,
  type PanelOffset,
} from "../../../components/WorkflowDraggablePanel.tsx";
import { CloseIcon, SyncIcon } from "../../../icons.tsx";
import { Component, lazy, Suspense, useMemo, useState, type ErrorInfo, type ReactNode } from "react";

function createLazyFinalCompositionEditor() {
  return lazy(() => import("./V2FinalCompositionEditor.tsx").then((module) => ({
    default: module.V2FinalCompositionEditor,
  })));
}

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
  const [loadAttempt, setLoadAttempt] = useState(0);
  const LazyFinalCompositionEditor = useMemo(createLazyFinalCompositionEditor, [loadAttempt]);
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
        <FinalCompositionEditorErrorBoundary
          key={loadAttempt}
          onRetry={() => setLoadAttempt((attempt) => attempt + 1)}
          onClose={onClose}
        >
          <Suspense fallback={<V2FinalCompositionEditorLoading />}>
            <LazyFinalCompositionEditor
              workflowId={workflowId}
              active
              onWorkflowRefresh={onWorkflowRefresh}
            />
          </Suspense>
        </FinalCompositionEditorErrorBoundary>
      </div>
    </WorkflowDraggablePanel>
  );
}

function V2FinalCompositionEditorLoading() {
  return <p className="v2-composition-editor-loading" role="status" aria-live="polite">Loading Final Composition editor...</p>;
}

class FinalCompositionEditorErrorBoundary extends Component<{
  children: ReactNode;
  onRetry: () => void;
  onClose: () => void;
}, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Final Composition editor failed to load", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="v2-composition-editor-load-error" role="alert">
        <strong>Final Composition editor could not be loaded.</strong>
        <p>The workflow remains available. Retry the editor chunk or close this panel.</p>
        <div className="v2-composition-editor-load-error-actions">
          <button type="button" onClick={this.props.onRetry}>
            <SyncIcon />
            <span>Retry loading editor</span>
          </button>
          <button type="button" onClick={this.props.onClose}>
            <CloseIcon />
            <span>Close editor</span>
          </button>
        </div>
      </div>
    );
  }
}
