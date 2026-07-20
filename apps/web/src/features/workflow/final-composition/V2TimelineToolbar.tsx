import {
  FitIcon,
  PlayIcon,
  PollIcon,
  RedoIcon,
  SaveIcon,
  UndoIcon,
} from "../../../icons.tsx";
import type {
  V2FinalCompositionEditMode,
  V2FinalCompositionTool,
} from "./useV2FinalCompositionEditor.ts";

type V2TimelineToolbarProps = {
  tool: V2FinalCompositionTool;
  editMode: V2FinalCompositionEditMode;
  snapEnabled: boolean;
  zoom: number;
  playing: boolean;
  canUndo: boolean;
  canRedo: boolean;
  canSave: boolean;
  canRender: boolean;
  loading: boolean;
  saving: boolean;
  rendering: boolean;
  onSetTool: (tool: V2FinalCompositionTool) => void;
  onSetEditMode: (mode: V2FinalCompositionEditMode) => void;
  onToggleSnap: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onFitTimeline: () => void;
  onTogglePlaying: () => void;
  onRefresh: () => void;
  onSave: () => void;
  onRender: () => void;
};

export function V2TimelineToolbar({
  tool,
  editMode,
  snapEnabled,
  zoom,
  playing,
  canUndo,
  canRedo,
  canSave,
  canRender,
  loading,
  saving,
  rendering,
  onSetTool,
  onSetEditMode,
  onToggleSnap,
  onUndo,
  onRedo,
  onZoomOut,
  onZoomIn,
  onFitTimeline,
  onTogglePlaying,
  onRefresh,
  onSave,
  onRender,
}: V2TimelineToolbarProps) {
  return (
    <div className="v2-composition-editor-toolbar v2-timeline-toolbar" aria-label="Timeline tools">
      <div className="v2-composition-toolbar-actions" role="toolbar" aria-label="Editing tools">
        <ToolbarButton
          label="Select tool"
          pressed={tool === "select"}
          onClick={() => onSetTool("select")}
        >
          <span aria-hidden="true">V</span>
        </ToolbarButton>
        <ToolbarButton
          label="Blade tool"
          pressed={tool === "blade"}
          onClick={() => onSetTool("blade")}
        >
          <span aria-hidden="true">B</span>
        </ToolbarButton>
        <div className="v2-timeline-mode-control" role="group" aria-label="Trim mode">
          <button
            type="button"
            aria-pressed={editMode === "normal"}
            title="Normal trim"
            onClick={() => onSetEditMode("normal")}
          >
            Normal
          </button>
          <button
            type="button"
            aria-pressed={editMode === "ripple"}
            title="Ripple trim"
            onClick={() => onSetEditMode("ripple")}
          >
            Ripple
          </button>
        </div>
        <ToolbarButton
          label={snapEnabled ? "Disable Snapping" : "Enable Snapping"}
          pressed={snapEnabled}
          onClick={onToggleSnap}
        >
          <span aria-hidden="true">S</span>
        </ToolbarButton>
        <ToolbarButton label="Undo" disabled={!canUndo} onClick={onUndo}>
          <UndoIcon />
        </ToolbarButton>
        <ToolbarButton label="Redo" disabled={!canRedo} onClick={onRedo}>
          <RedoIcon />
        </ToolbarButton>
        <ToolbarButton label="Zoom out" onClick={onZoomOut}>
          <span aria-hidden="true">-</span>
        </ToolbarButton>
        <output aria-label="Timeline zoom">{Math.round(zoom * 100)}%</output>
        <ToolbarButton label="Zoom in" onClick={onZoomIn}>
          <span aria-hidden="true">+</span>
        </ToolbarButton>
        <ToolbarButton label="Fit timeline" onClick={onFitTimeline}>
          <FitIcon />
        </ToolbarButton>
      </div>
      <div className="v2-composition-toolbar-actions" role="toolbar" aria-label="Playback and timeline actions">
        <ToolbarButton label={playing ? "Pause preview" : "Play preview"} onClick={onTogglePlaying}>
          {playing ? <span aria-hidden="true">II</span> : <PlayIcon />}
        </ToolbarButton>
        <ToolbarButton label="Refresh timeline" disabled={loading} onClick={onRefresh}>
          <PollIcon />
        </ToolbarButton>
        <ToolbarButton label={saving ? "Saving timeline" : "Save timeline"} disabled={!canSave} onClick={onSave}>
          <SaveIcon />
        </ToolbarButton>
        <ToolbarButton label={rendering ? "Rendering final video" : "Render final video"} disabled={!canRender} onClick={onRender}>
          <PlayIcon />
        </ToolbarButton>
      </div>
    </div>
  );
}

function ToolbarButton({
  label,
  pressed,
  disabled,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      className="v2-composition-icon-button"
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
