interface EditingNodeSurfaceProps {
  onOpenEditing?: () => void;
}

export function EditingNodeSurface({ onOpenEditing }: EditingNodeSurfaceProps) {
  return (
    <div className="agent-canvas-node__editing-surface">
      <button
        className="agent-canvas-node__editing-entry nodrag nopan"
        type="button"
        aria-label="Open editing editor"
        title="Open editing editor"
        disabled={!onOpenEditing}
        onPointerDown={(event) => event.stopPropagation()}
        onDoubleClick={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onOpenEditing?.();
        }}
      >
        <img
          src="/imgs/node-icons/scissors.svg"
          alt=""
          aria-hidden="true"
          draggable={false}
        />
      </button>
    </div>
  );
}
