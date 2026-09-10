import { useEffect, useMemo, useState } from "react";

import { PlusIcon, TrashIcon } from "../../../icons.tsx";
import type { CanvasPositionV2 } from "../../../types-v2.ts";
import type { AgentCanvasVisibleNodeTypeV2 } from "../model/nodeDefaults.ts";
import { AgentCanvasNodePicker } from "./AgentCanvasNodePicker.tsx";

interface AgentCanvasContextMenuBaseProps {
  menuPosition: CanvasPositionV2;
  onClose: () => void;
  onRelocate?: (menuPosition: CanvasPositionV2) => void;
}

type AgentCanvasContextMenuProps = AgentCanvasContextMenuBaseProps & (
  | {
    canvasPosition: CanvasPositionV2;
    onCreateNode: (nodeType: AgentCanvasVisibleNodeTypeV2, position: CanvasPositionV2) => void;
    onDeleteNode?: never;
  }
  | {
    canvasPosition?: never;
    onCreateNode?: never;
    onDeleteNode: () => void;
  }
);

const MENU_WIDTH = 212;
const ACTION_MENU_HEIGHT = 58;
const NODE_PICKER_MENU_HEIGHT = 252;
const VIEWPORT_GUTTER = 12;

function boundedMenuPosition(position: CanvasPositionV2, menuHeight: number): CanvasPositionV2 {
  return {
    x: Math.max(VIEWPORT_GUTTER, Math.min(position.x, window.innerWidth - MENU_WIDTH - VIEWPORT_GUTTER)),
    y: Math.max(VIEWPORT_GUTTER, Math.min(position.y, window.innerHeight - menuHeight - VIEWPORT_GUTTER)),
  };
}

export function AgentCanvasContextMenu({
  menuPosition,
  canvasPosition,
  onCreateNode,
  onDeleteNode,
  onClose,
  onRelocate,
}: AgentCanvasContextMenuProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const menuHeight = pickerOpen ? NODE_PICKER_MENU_HEIGHT : ACTION_MENU_HEIGHT;
  const boundedPosition = useMemo(
    () => boundedMenuPosition(menuPosition, menuHeight),
    [menuHeight, menuPosition],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <>
      <button
        type="button"
        className="agent-canvas-context-menu__backdrop"
        aria-label="Close canvas menu"
        onClick={onClose}
        onContextMenu={(event) => {
          event.preventDefault();
          setPickerOpen(false);
          onRelocate?.({ x: event.clientX, y: event.clientY });
        }}
      />
      <div
        className="agent-canvas-context-menu"
        role="menu"
        aria-label="Canvas actions"
        style={{ left: boundedPosition.x, top: boundedPosition.y }}
        onContextMenu={(event) => event.preventDefault()}
      >
        {onDeleteNode ? (
          <button
            type="button"
            className="agent-canvas-context-menu__action"
            role="menuitem"
            autoFocus
            onClick={onDeleteNode}
          >
            <TrashIcon />
            <span>Delete node</span>
          </button>
        ) : pickerOpen && canvasPosition && onCreateNode ? (
          <AgentCanvasNodePicker
            className="agent-canvas-node-picker agent-canvas-context-menu__node-picker"
            menuLabel="Add node types"
            onSelect={(nodeType) => onCreateNode(nodeType, canvasPosition)}
          />
        ) : (
          <button
            type="button"
            className="agent-canvas-context-menu__action"
            role="menuitem"
            autoFocus
            onClick={() => setPickerOpen(true)}
          >
            <PlusIcon />
            <span>Add node</span>
          </button>
        )}
      </div>
    </>
  );
}
