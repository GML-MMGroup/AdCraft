import {
  FitIcon,
  LayoutIcon,
  PlayIcon,
  ProjectCreateIcon,
  RedoIcon,
  SaveIcon,
  TrashIcon,
  UndoIcon,
} from "../../../icons";

export type WorkflowBottomToolbarModel = {
  workflowRunning: boolean;
  saving: boolean;
  canUndo: boolean;
  canRedo: boolean;
  canDeleteSelection: boolean;
  toolbarStatus: string;
};

type ToolbarActionResult = unknown | Promise<unknown>;

export type WorkflowBottomToolbarActions = {
  createNewProject: () => void;
  runWorkflow: () => ToolbarActionResult;
  saveCanvas: () => ToolbarActionResult;
  undoCanvas: () => void;
  redoCanvas: () => void;
  deleteSelection: () => ToolbarActionResult;
  autoLayout: () => void;
  fitView: () => void;
};

export function WorkflowBottomToolbar({
  model,
  actions,
}: {
  model: WorkflowBottomToolbarModel;
  actions: WorkflowBottomToolbarActions;
}) {
  return (
    <div className="bottom-toolbar">
      <button className="tool-btn workflow-new-project" type="button" title="New project" aria-label="New project" onClick={actions.createNewProject}>
        <ProjectCreateIcon />
      </button>
      <button className="tool-btn" title={model.workflowRunning ? "Workflow running" : "Run workflow"} aria-label={model.workflowRunning ? "Workflow running" : "Run workflow"} disabled={model.workflowRunning} onClick={() => void actions.runWorkflow()}>
        <PlayIcon />
      </button>
      <button className="tool-btn" title={model.saving ? "Saving canvas" : "Save canvas"} aria-label={model.saving ? "Saving canvas" : "Save canvas"} onClick={() => void actions.saveCanvas()}>
        <SaveIcon />
      </button>
      <button className="tool-btn" title="Undo" aria-label="Undo" disabled={!model.canUndo} onClick={actions.undoCanvas}>
        <UndoIcon />
      </button>
      <button className="tool-btn" title="Redo" aria-label="Redo" disabled={!model.canRedo} onClick={actions.redoCanvas}>
        <RedoIcon />
      </button>
      <button className="tool-btn" title="Delete selection" aria-label="Delete selection" disabled={!model.canDeleteSelection} onClick={() => void actions.deleteSelection()}>
        <TrashIcon />
      </button>
      <button className="tool-btn" title="Auto layout" aria-label="Auto layout" onClick={actions.autoLayout}>
        <LayoutIcon />
      </button>
      <button className="tool-btn" title="Fit view" aria-label="Fit view" onClick={actions.fitView}>
        <FitIcon />
      </button>
      <span className="toolbar-status">{model.toolbarStatus}</span>
    </div>
  );
}
