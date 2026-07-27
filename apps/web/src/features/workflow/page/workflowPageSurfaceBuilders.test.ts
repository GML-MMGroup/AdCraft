import { describe, expect, it, vi } from "vitest";
import type { AssetLibraryEntitySummary } from "../../../types.ts";
import {
  buildWorkflowBottomToolbarSurface,
  selectWorkflowPickerEntity,
  workflowPageFloatingEditorVisibility,
  workflowPageSurfaceVisibility,
} from "./workflowPageSurfaceBuilders.ts";

const noop = () => undefined;

describe("workflow page surface builders", () => {
  it("preserves toolbar execution, runtime, save, and selection status", () => {
    const surface = buildWorkflowBottomToolbarSurface({
      status: "Running",
      activeExecutionId: "execution-42",
      workflowRunExecutionId: "execution-old",
      executionPollingState: "polling",
      runtimeConnectionLabel: "runtime connected",
      savedAt: "not-a-date",
      canvasHistoryCount: 1,
      canvasFutureCount: 0,
      hasCanvasSelection: false,
      hasSelectedPlanNode: true,
      workflowRunning: true,
      saving: false,
      reactFlow: null,
      createNewProject: noop,
      runWorkflow: noop,
      saveCanvas: noop,
      undoCanvas: noop,
      redoCanvas: noop,
      deleteSelection: noop,
      autoLayout: noop,
    });

    expect(surface.model).toMatchObject({
      workflowRunning: true,
      canUndo: true,
      canRedo: false,
      canDeleteSelection: true,
    });
    expect(surface.model.toolbarStatus).toBe(
      "Running · execution-42 · polling · runtime connected · saved not-a-date",
    );
  });

  it("keeps the retired workbench out of every workflow and opens only the V2 final composition panel", () => {
    expect(workflowPageSurfaceVisibility({
      isV2: false,
      detailsOpen: true,
      selectedNodeId: "storyboard",
      workflowId: "workflow-v1",
    })).toEqual({
      showV2FinalComposition: false,
    });

    expect(workflowPageSurfaceVisibility({
      isV2: true,
      detailsOpen: true,
      selectedNodeId: "final-composition",
      workflowId: "workflow-v2",
    })).toEqual({
      showV2FinalComposition: true,
    });
  });

  it("opens V2 slot and storyboard composers only for active editable targets", () => {
    expect(workflowPageFloatingEditorVisibility({
      isV2: true,
      hasActiveSlotId: true,
      slotIsEditable: true,
      hasSlotDraft: true,
      hasActiveStoryboardItemId: true,
      hasStoryboardItem: true,
    })).toEqual({
      showSlotComposer: true,
      showStoryboardComposer: true,
    });

    expect(workflowPageFloatingEditorVisibility({
      isV2: false,
      hasActiveSlotId: true,
      slotIsEditable: true,
      hasSlotDraft: true,
      hasActiveStoryboardItemId: true,
      hasStoryboardItem: true,
    })).toEqual({
      showSlotComposer: false,
      showStoryboardComposer: false,
    });
  });

  it("replaces a V2 slot once and closes the picker", () => {
    const entity: AssetLibraryEntitySummary = {
      entity_id: "entity-1",
      entity_type: "character",
      display_name: "Character",
      tags: [],
      asset_count: 1,
      is_archived: false,
    };
    const replace = vi.fn();
    const toggle = vi.fn();
    const close = vi.fn();

    selectWorkflowPickerEntity({
      pickerTarget: "v2-slot-replace",
      activeV2SlotId: "slot-1",
      entity,
      replaceV2SlotWithLibraryEntity: replace,
      toggleLibraryEntityForTarget: toggle,
      closePicker: close,
    });

    expect(replace).toHaveBeenCalledWith("slot-1", entity);
    expect(toggle).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
  });

  it("keeps the picker open while toggling a multi-select entity", () => {
    const entity: AssetLibraryEntitySummary = {
      entity_id: "entity-2",
      entity_type: "scene",
      display_name: "Scene",
      tags: [],
      asset_count: 1,
      is_archived: false,
    };
    const replace = vi.fn();
    const toggle = vi.fn();
    const close = vi.fn();

    selectWorkflowPickerEntity({
      pickerTarget: "prompt",
      activeV2SlotId: null,
      entity,
      replaceV2SlotWithLibraryEntity: replace,
      toggleLibraryEntityForTarget: toggle,
      closePicker: close,
    });

    expect(toggle).toHaveBeenCalledWith("prompt", entity);
    expect(replace).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  });
});
