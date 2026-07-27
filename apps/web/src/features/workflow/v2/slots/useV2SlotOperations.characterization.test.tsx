import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "../../../../api/v2Client.ts";
import {
  normalizeAssetVersionV2,
  normalizeSlotVersionsResponseV2,
  normalizeWorkflowAssetRelationV2,
  normalizeWorkflowItemV2,
  normalizeWorkflowSlotV2,
  normalizeWorkflowV2,
} from "../../../../api/v2Normalizers.ts";
import {
  FINAL_COMPOSITION_EVENT_NAME,
  FINAL_COMPOSITION_SOURCE_SELECTION_EVENT,
} from "../../final-composition/finalCompositionEvents.ts";
import type { SlotMicroEditDraft } from "./useSlotMicroEdit.ts";
import { useV2SlotOperations } from "./useV2SlotOperations.ts";

function makeSlot(overrides: Record<string, unknown> = {}) {
  return normalizeWorkflowSlotV2({
    slot_id: "slot-1",
    node_id: "node-1",
    item_id: "item-1",
    slot_type: "product_image",
    media_type: "image",
    required: true,
    status: "completed",
    slot_prompt: "Original prompt",
    selected_asset_id: "selected-asset",
    selected_version_id: "selected-version",
    ...overrides,
  });
}

function makeItem(overrides: Record<string, unknown> = {}) {
  return normalizeWorkflowItemV2({
    item_id: "item-1",
    node_id: "node-1",
    item_type: "storyboard_shot",
    display_name: "Shot 1",
    status: "ready",
    lifecycle_state: "active",
    shot_id: "shot-1",
    shot_summary_prompt: "Existing summary",
    ...overrides,
  });
}

function makeAsset(assetId: string, versionId: string, mediaType: "image" | "audio" = "image") {
  return normalizeAssetVersionV2({
    asset_id: assetId,
    version_id: versionId,
    media_type: mediaType,
    source_type: "generated",
    semantic_type: mediaType === "audio" ? "bgm_audio" : "product_image",
    public_url: `/media/${versionId}`,
  });
}

function makeWorkflow(options: {
  slot?: ReturnType<typeof makeSlot>;
  item?: ReturnType<typeof makeItem>;
  assets?: ReturnType<typeof makeAsset>[];
} = {}) {
  const slot = options.slot ?? makeSlot();
  const item = options.item ?? makeItem();
  return normalizeWorkflowV2({
    workflow_id: "workflow-1",
    workflow_schema_version: 2,
    nodes: [],
    edges: [],
    items: [item],
    slots: [slot],
    asset_versions: options.assets ?? [
      makeAsset("selected-asset", "selected-version"),
      makeAsset("working-asset", "working-version"),
    ],
  });
}

function makeDraft(overrides: Partial<SlotMicroEditDraft> = {}): SlotMicroEditDraft {
  return {
    prompt: "Original prompt",
    negative_prompt: "",
    reference_asset_ids: [],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: [],
    dirty: false,
    promptDirty: false,
    referenceDirty: false,
    base_prompt: "Original prompt",
    base_negative_prompt: "",
    isSubmitting: false,
    submissionDepth: 0,
    promptRevision: 0,
    referenceRevision: 0,
    ...overrides,
  };
}

function createHarness(options: {
  workflow?: ReturnType<typeof makeWorkflow>;
  draft?: SlotMicroEditDraft;
  selectedFreeGenerationMediaType?: string | null;
} = {}) {
  const workflow = options.workflow ?? makeWorkflow();
  const slot = workflow.slots[0];
  const item = workflow.items[0];
  const order: string[] = [];
  const setStatus = vi.fn();
  const setSubmitting = vi.fn((slotId: string, submitting: boolean) => {
    order.push(`submitting:${slotId}:${submitting}`);
  });
  const markClean = vi.fn(() => {
    order.push("mark-clean");
  });
  const microEdit = {
    state: {
      openSlotId: slot.slot_id,
      draftsBySlotId: options.draft ? { [slot.slot_id]: options.draft } : {},
    },
    setState: vi.fn(),
    openSlot: vi.fn(),
    closeSlot: vi.fn(),
    updatePrompt: vi.fn(),
    updateNegativePrompt: vi.fn(),
    addReference: vi.fn(),
    removeReference: vi.fn(),
    addAttachment: vi.fn(),
    updateAttachment: vi.fn(),
    setSubmitting,
    markClean,
    discardDraft: vi.fn(),
    rebaseSlots: vi.fn(),
  };
  const applyWorkflowV2 = vi.fn(async () => {
    order.push("apply-workflow");
  });
  const refreshV2WorkflowGraph = vi.fn(async () => {
    order.push("refresh-workflow");
    return workflow;
  });
  const syncV2Snapshot = vi.fn(async () => {
    order.push("sync-snapshot");
  });
  const refreshV2AssetsAndRetryMissing = vi.fn(async () => {
    order.push("refresh-assets");
  });
  const setV2SlotVersionsById = vi.fn(() => {
    order.push("store-versions");
  });
  const args: Parameters<typeof useV2SlotOperations>[0] = {
    workflowId: workflow.workflow_id,
    workflowV2: workflow,
    currentWorkflowIsV2: () => true,
    activeWorkflowIdRef: { current: workflow.workflow_id },
    selectedPlanNode: { id: slot.node_id },
    selectedV2Items: [item],
    selectedV2Slots: [slot],
    allV2Slots: [slot],
    selectedV2AssetVersions: new Map(workflow.asset_versions.map((asset) => [asset.version_id, asset])),
    selectedAssets: [],
    activeV2SlotId: slot.slot_id,
    selectedFreeGenerationMediaType: options.selectedFreeGenerationMediaType ?? "image",
    dynamicItemPromptDrafts: {},
    v2SlotVersionsById: {
      [slot.slot_id]: normalizeSlotVersionsResponseV2({
        workflow_id: workflow.workflow_id,
        slot_id: slot.slot_id,
        selected_asset_id: slot.selected_asset_id,
        current_working_version_id: slot.current_working_version_id,
        versions: workflow.asset_versions,
      }),
    },
    v2SlotMicroEdit: microEdit,
    setStatus,
    setSelectedNodeId: vi.fn(),
    setDynamicItemPromptSavingById: vi.fn(),
    setDynamicItemPromptDrafts: vi.fn(),
    setV2SlotVersionsById,
    applyWorkflowV2,
    refreshV2WorkflowGraph,
    syncV2Snapshot,
    refreshV2AssetsAndRetryMissing,
    captureV2WorkflowApplicationRevision: (workflowId) => ({ workflowId, revision: 1 }),
    isCurrentV2WorkflowApplicationRevision: () => true,
    selectedNodeIdRef: { current: slot.node_id },
  };
  const rendered = renderHook(() => useV2SlotOperations(args));
  return {
    actions: rendered.result.current.actions,
    args,
    workflow,
    slot,
    item,
    order,
    setStatus,
    setSubmitting,
    markClean,
    applyWorkflowV2,
    refreshV2WorkflowGraph,
    syncV2Snapshot,
    refreshV2AssetsAndRetryMissing,
    setV2SlotVersionsById,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useV2SlotOperations characterization", () => {
  it("flushes prompt before references, then cleans the draft and propagates a failed flush", async () => {
    const draft = makeDraft({
      prompt: "Persisted before run",
      dirty: true,
      promptDirty: true,
      referenceDirty: true,
      attachments: [{
        id: "reference:asset-ref",
        source: "reference_asset",
        source_asset_id: "asset-ref",
        semantic_type: "product_image",
        status: "registered",
      }],
    });
    const harness = createHarness({ draft });
    const updatedWorkflow = makeWorkflow({ slot: makeSlot({ slot_prompt: draft.prompt }) });
    const update = vi.spyOn(v2Api, "updateSlotPrompt").mockImplementation(async () => {
      harness.order.push("update-prompt");
      return updatedWorkflow;
    });
    const attach = vi.spyOn(v2Api, "attachReference").mockImplementation(async () => {
      harness.order.push("attach-reference");
      return {
        workflow: updatedWorkflow,
        relation: normalizeWorkflowAssetRelationV2({
          relation_id: "relation-1",
          relation_type: "reference_for_slot",
          workflow_id: "workflow-1",
          slot_id: "slot-1",
          source_asset_id: "asset-ref",
        }),
        assets: [],
      };
    });

    await act(async () => {
      await harness.actions.flushV2SlotDrafts();
    });

    expect(update).toHaveBeenCalledWith("workflow-1", "slot-1", {
      slot_prompt: "Persisted before run",
      negative_prompt: "",
    });
    expect(attach).toHaveBeenCalledWith("workflow-1", expect.objectContaining({
      target_type: "slot",
      target_id: "slot-1",
      source_asset_id: "asset-ref",
    }));
    expect(harness.order.indexOf("update-prompt")).toBeLessThan(harness.order.indexOf("attach-reference"));
    expect(harness.markClean).toHaveBeenCalledWith("slot-1", expect.objectContaining({ slot_prompt: draft.prompt }), true);
    expect(harness.setSubmitting.mock.calls).toEqual([
      ["slot-1", true],
      ["slot-1", false],
    ]);

    update.mockRejectedValueOnce(new Error("etag conflict"));
    await expect(harness.actions.flushV2SlotDrafts()).rejects.toThrow("etag conflict");
    expect(harness.setSubmitting).toHaveBeenLastCalledWith("slot-1", false, "etag conflict");
    expect(harness.setStatus).toHaveBeenLastCalledWith("etag conflict");
  });

  it("deduplicates prompt references and attaches them before regenerating", async () => {
    const harness = createHarness();
    vi.spyOn(v2Api, "attachReference").mockImplementation(async () => {
      harness.order.push("attach-reference");
      return { workflow: harness.workflow, relation: null, assets: [] };
    });
    vi.spyOn(v2Api, "regenerateSlot").mockImplementation(async () => {
      harness.order.push("regenerate");
      return { workflow: harness.workflow, task: null };
    });
    vi.spyOn(v2Api, "slotVersions").mockResolvedValue(normalizeSlotVersionsResponseV2({
      workflow_id: "workflow-1",
      slot_id: "slot-1",
      versions: harness.workflow.asset_versions,
    }));

    await act(async () => {
      await harness.actions.submitV2LocalSlotPrompt("slot-1", "Original prompt", {
        asset_references: [
          { reference_source: "reference_asset", asset_id: "asset-ref", role: "product_image" },
          { reference_source: "reference_asset", asset_id: "asset-ref", role: "product_image" },
        ],
      });
    });

    expect(v2Api.attachReference).toHaveBeenCalledTimes(1);
    expect(harness.order.indexOf("attach-reference")).toBeLessThan(harness.order.indexOf("regenerate"));
  });

  it("marks a failed library attachment and clears submission after registration errors", async () => {
    const harness = createHarness();
    const failure = new Error("library registration failed");
    vi.spyOn(v2Api, "registerLibraryReference").mockRejectedValue(failure);

    await act(async () => {
      await harness.actions.selectV2SlotLibraryReference("slot-1", "entity-1");
    });

    expect(harness.setSubmitting.mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(harness.args.v2SlotMicroEdit.addAttachment).mock.invocationCallOrder[0],
    );
    expect(harness.args.v2SlotMicroEdit.updateAttachment).toHaveBeenCalledWith(
      "slot-1",
      "library:entity-1:",
      { status: "failed", error: "library registration failed" },
    );
    expect(harness.setSubmitting).toHaveBeenLastCalledWith(
      "slot-1",
      false,
      "library registration failed",
    );
    expect(harness.setStatus).toHaveBeenLastCalledWith(
      "library registration failed",
    );
  });

  it("persists a dirty prompt before regenerate and completes refreshes in workflow-assets-snapshot-versions-clean order", async () => {
    const draft = makeDraft({ prompt: "New prompt", dirty: true, promptDirty: true });
    const regeneratedSlot = makeSlot({
      slot_prompt: "New prompt",
      current_working_asset_id: "working-asset",
      current_working_version_id: "working-version",
    });
    const regeneratedWorkflow = makeWorkflow({ slot: regeneratedSlot });
    const harness = createHarness({ draft });
    vi.spyOn(v2Api, "updateSlotPrompt").mockImplementation(async () => {
      harness.order.push("update-prompt");
      return makeWorkflow({ slot: makeSlot({ slot_prompt: "New prompt" }) });
    });
    vi.spyOn(v2Api, "regenerateSlot").mockImplementation(async () => {
      harness.order.push("regenerate");
      return { workflow: regeneratedWorkflow, task: null };
    });
    vi.spyOn(v2Api, "slotVersions").mockImplementation(async () => {
      harness.order.push("load-versions");
      return normalizeSlotVersionsResponseV2({
        workflow_id: "workflow-1",
        slot_id: "slot-1",
        selected_asset_id: "selected-asset",
        current_working_version_id: "working-version",
        versions: regeneratedWorkflow.asset_versions,
      });
    });

    await act(async () => {
      await harness.actions.submitV2SlotMicroPrompt("slot-1");
    });

    expect(v2Api.updateSlotPrompt).toHaveBeenCalledBefore(vi.mocked(v2Api.regenerateSlot));
    expect(regeneratedSlot.selected_asset_id).toBe("selected-asset");
    expect(regeneratedSlot.current_working_version_id).toBe("working-version");
    expect(harness.order).toEqual([
      "submitting:slot-1:true",
      "update-prompt",
      "apply-workflow",
      "regenerate",
      "apply-workflow",
      "refresh-assets",
      "sync-snapshot",
      "load-versions",
      "store-versions",
      "mark-clean",
      "submitting:slot-1:false",
    ]);
    expect(harness.applyWorkflowV2).toHaveBeenLastCalledWith(regeneratedWorkflow, { refreshAssetsReason: false });
    expect(harness.markClean).toHaveBeenCalledWith("slot-1", regeneratedSlot, true);
  });

  it("selects the exact asset/version, notifies BGM media, then refreshes workflow, snapshot, and versions", async () => {
    const bgmSlot = makeSlot({
      slot_type: "bgm_audio",
      media_type: "audio",
      selected_asset_id: "selected-audio",
      selected_version_id: "audio-v1",
      current_working_asset_id: "working-audio",
      current_working_version_id: "audio-v2",
    });
    const selected = makeAsset("selected-audio", "audio-v1", "audio");
    const working = makeAsset("working-audio", "audio-v2", "audio");
    const harness = createHarness({ workflow: makeWorkflow({ slot: bgmSlot, assets: [selected, working] }) });
    const events: CustomEvent[] = [];
    const listener = (event: Event) => events.push(event as CustomEvent);
    window.addEventListener(FINAL_COMPOSITION_EVENT_NAME, listener);
    vi.spyOn(v2Api, "selectSlotVersion").mockResolvedValue({});
    vi.spyOn(v2Api, "slotVersions").mockImplementation(async () => {
      harness.order.push("load-versions");
      return normalizeSlotVersionsResponseV2({
        workflow_id: "workflow-1",
        slot_id: "slot-1",
        selected_asset_id: "working-audio",
        versions: [selected, working],
      });
    });

    await act(async () => {
      await harness.actions.selectV2SlotVersion("slot-1", "audio-v2");
    });
    window.removeEventListener(FINAL_COMPOSITION_EVENT_NAME, listener);

    expect(v2Api.selectSlotVersion).toHaveBeenCalledWith("workflow-1", "slot-1", {
      asset_id: "working-audio",
      version_id: "audio-v2",
      source_action: "slot_version_picker",
    });
    expect(events[0]?.detail).toEqual({
      workflowId: "workflow-1",
      eventTypes: [FINAL_COMPOSITION_SOURCE_SELECTION_EVENT],
      sourceSlotId: "slot-1",
    });
    expect(harness.order).toEqual([
      "refresh-workflow",
      "sync-snapshot",
      "load-versions",
      "store-versions",
    ]);
  });

  it("publishes provider task status before refreshing workflow and snapshot", async () => {
    const harness = createHarness();
    vi.spyOn(v2Api, "pollProviderTask").mockResolvedValue({
      task_id: "task-1",
      workflow_id: "workflow-1",
      status: "completed",
      task_type: "slot_generation",
      created_at: null,
      updated_at: null,
      metadata: {},
    });
    harness.setStatus.mockImplementation((status) => {
      harness.order.push(`status:${String(status)}`);
    });

    await act(async () => {
      await harness.actions.pollV2ProviderTask("task-1");
    });

    expect(harness.order).toEqual([
      "status:Provider task completed",
      "refresh-workflow",
      "sync-snapshot",
    ]);
  });

  it("confirms storyboard summaries from the draft and regenerates description before references and media refresh", async () => {
    const harness = createHarness();
    harness.args.dynamicItemPromptDrafts = { "item-1": "Draft summary" };
    vi.spyOn(v2Api, "confirmShotSummary").mockImplementation(async () => {
      harness.order.push("confirm-summary");
      return harness.workflow;
    });
    vi.spyOn(v2Api, "attachReference").mockImplementation(async () => {
      harness.order.push("attach-reference");
      return { workflow: harness.workflow, relation: null, assets: [] };
    });
    vi.spyOn(v2Api, "generateItem").mockImplementation(async () => {
      harness.order.push("generate-item");
      return { workflow: harness.workflow, task: null };
    });

    await act(async () => {
      await harness.actions.confirmV2ShotSummary(harness.item);
      await harness.actions.submitV2StoryboardPrompt(harness.item, "  Regenerated description  ", {
        asset_references: [{ reference_source: "reference_asset", asset_id: "story-ref" }],
      });
    });

    expect(v2Api.confirmShotSummary).toHaveBeenNthCalledWith(1, "workflow-1", "shot-1", "Draft summary");
    expect(v2Api.confirmShotSummary).toHaveBeenNthCalledWith(2, "workflow-1", "shot-1", "Regenerated description");
    expect(harness.order.indexOf("confirm-summary")).toBeLessThan(harness.order.indexOf("attach-reference"));
    expect(harness.order.indexOf("attach-reference")).toBeLessThan(harness.order.indexOf("generate-item"));
    expect(harness.order.slice(-3)).toEqual(["apply-workflow", "refresh-assets", "sync-snapshot"]);
    expect(harness.args.setDynamicItemPromptSavingById).toHaveBeenLastCalledWith(expect.any(Function));
  });

  it("preserves create, generate, absorb, and delete free-node payloads and workflow application", async () => {
    const harness = createHarness();
    vi.spyOn(v2Api, "createFreeNode").mockResolvedValue(harness.workflow);
    vi.spyOn(v2Api, "generateFreeNode").mockResolvedValue({ workflow: harness.workflow, task: null });
    vi.spyOn(v2Api, "absorbFreeNode").mockResolvedValue({
      workflow: harness.workflow,
      relations: [normalizeWorkflowAssetRelationV2({ relation_id: "absorbed-1" })],
    });
    vi.spyOn(v2Api, "deleteFreeNode").mockResolvedValue(harness.workflow);

    await act(async () => {
      await harness.actions.createV2FreeNode();
      await harness.actions.generateV2FreeNode("free-node");
      await harness.actions.absorbV2FreeNode("free-node", "free-asset", "product-generation");
      await harness.actions.deleteV2FreeNode("free-node");
    });

    expect(v2Api.createFreeNode).toHaveBeenCalledWith("workflow-1", { slot_prompt: "New free generation" });
    expect(v2Api.generateFreeNode).toHaveBeenCalledWith("workflow-1", "free-node", { output_media_type: "image" });
    expect(v2Api.absorbFreeNode).toHaveBeenCalledWith("workflow-1", "free-node", {
      target_node_id: "product-generation",
      asset_id: "free-asset",
      absorb_role: "reference",
    });
    expect(v2Api.deleteFreeNode).toHaveBeenCalledWith("workflow-1", "free-node");
    expect(harness.applyWorkflowV2).toHaveBeenCalledTimes(4);
    expect(harness.syncV2Snapshot).toHaveBeenCalledTimes(1);
  });

  it("rejects an incompatible free-node absorb target without a backend call", async () => {
    const harness = createHarness({ selectedFreeGenerationMediaType: "audio" });
    const absorb = vi.spyOn(v2Api, "absorbFreeNode");

    await act(async () => {
      await harness.actions.absorbV2FreeNode("free-node", "free-asset", "product");
    });

    expect(absorb).not.toHaveBeenCalled();
    expect(harness.setStatus).toHaveBeenCalledWith("Cannot absorb audio asset into product.");
  });
});
