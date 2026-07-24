import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "../../../../api/v2Client.ts";
import { v2AuthoringConflictStore } from "../../../../api/v2AuthoringConflictStore.ts";
import { v2EtagStore } from "../../../../api/v2EtagStore.ts";
import {
  normalizeAssetVersionV2,
  normalizeWorkflowItemV2,
  normalizeWorkflowSlotV2,
  normalizeWorkflowV2,
} from "../../../../api/v2Normalizers.ts";
import type { SlotMicroEditDraft } from "./useSlotMicroEdit.ts";
import { useV2SlotOperations } from "./useV2SlotOperations.ts";

type HookArgs = Parameters<typeof useV2SlotOperations>[0];

const slot = normalizeWorkflowSlotV2({
  slot_id: "slot-1",
  node_id: "node-1",
  item_id: "item-1",
  slot_type: "product_image",
  media_type: "image",
  status: "completed",
  required: true,
  slot_prompt: "Original prompt",
  negative_prompt: "Original negative",
  explicit_reference_ids: [],
});

const storyboardItem = normalizeWorkflowItemV2({
  item_id: "shot-item-1",
  node_id: "storyboard",
  item_type: "storyboard_shot",
  display_name: "Shot one",
  shot_id: "shot-1",
  status: "completed",
  lifecycle_state: "active",
  item_prompt: "Original description",
});

function workflow(slots = [slot]) {
  return normalizeWorkflowV2({
    workflow_id: "workflow-1",
    workflow_schema_version: 2,
    nodes: [],
    items: [storyboardItem],
    slots,
    asset_versions: [],
    edges: [],
  });
}

function draft(overrides: Partial<SlotMicroEditDraft> = {}): SlotMicroEditDraft {
  return {
    prompt: "Original prompt",
    negative_prompt: "Original negative",
    reference_asset_ids: [],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: [],
    dirty: false,
    promptDirty: false,
    referenceDirty: false,
    base_prompt: "Original prompt",
    base_negative_prompt: "Original negative",
    isSubmitting: false,
    promptRevision: 0,
    referenceRevision: 0,
    ...overrides,
  };
}

function createHarness(overrides: Partial<HookArgs> = {}) {
  const events: string[] = [];
  const currentWorkflow = workflow();
  const v2SlotMicroEdit = {
    state: { openSlotId: null, draftsBySlotId: {} },
    setState: vi.fn(),
    openSlot: vi.fn(),
    closeSlot: vi.fn(),
    updatePrompt: vi.fn(),
    updateNegativePrompt: vi.fn(),
    addReference: vi.fn(),
    removeReference: vi.fn(),
    addAttachment: vi.fn(),
    updateAttachment: vi.fn(),
    setSubmitting: vi.fn((slotId: string, submitting: boolean, error?: string) => {
      events.push(`submitting:${slotId}:${submitting}:${error ?? ""}`);
    }),
    markClean: vi.fn((slotId: string) => events.push(`clean:${slotId}`)),
    discardDraft: vi.fn(),
    rebaseSlots: vi.fn(),
  } as unknown as HookArgs["v2SlotMicroEdit"];
  const setStatus = vi.fn((value: string | ((current: string) => string)) => {
    events.push(`status:${typeof value === "function" ? value("") : value}`);
  });
  const args: HookArgs = {
    workflowId: "workflow-1",
    workflowV2: currentWorkflow,
    currentWorkflowIsV2: () => true,
    activeWorkflowIdRef: { current: "workflow-1" },
    selectedPlanNode: { id: "node-1" },
    selectedV2Items: [storyboardItem],
    selectedV2Slots: [slot],
    allV2Slots: [slot],
    selectedV2AssetVersions: new Map(),
    selectedAssets: [],
    activeV2SlotId: "slot-1",
    selectedFreeGenerationMediaType: "image",
    dynamicItemPromptDrafts: {},
    v2SlotVersionsById: {},
    v2SlotMicroEdit,
    setStatus,
    setSelectedNodeId: vi.fn(),
    setDynamicItemPromptSavingById: vi.fn(),
    setDynamicItemPromptDrafts: vi.fn(),
    setV2SlotVersionsById: vi.fn(),
    applyWorkflowV2: vi.fn(async () => {
      events.push("apply");
    }),
    refreshV2WorkflowGraph: vi.fn(async () => {
      events.push("refresh-workflow");
      return currentWorkflow;
    }),
    syncV2Snapshot: vi.fn(async () => {
      events.push("snapshot");
    }),
    refreshV2AssetsAndRetryMissing: vi.fn(async () => {
      events.push("refresh-assets");
    }),
    captureV2WorkflowApplicationRevision: vi.fn(() => ({
      workflowId: "workflow-1",
      revision: 1,
    })),
    isCurrentV2WorkflowApplicationRevision: vi.fn(() => true),
    selectedNodeIdRef: { current: "" },
    ...overrides,
  };
  return { args, events, setStatus, v2SlotMicroEdit };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  v2EtagStore.clear();
  v2AuthoringConflictStore.clear();
});

describe("useV2SlotOperations public facade", () => {
  it("keeps the complete public action surface compatible", () => {
    const { args } = createHarness();
    const { result } = renderHook(() => useV2SlotOperations(args));

    expect(Object.keys(result.current.actions)).toEqual([
      "saveV2ItemPrompt",
      "saveV2SlotPrompt",
      "v2SlotById",
      "setActiveV2SlotId",
      "openV2SlotEditor",
      "changeV2SlotPrompt",
      "changeV2SlotNegativePrompt",
      "syncV2SlotPromptReferences",
      "uploadV2SlotReference",
      "selectV2SlotLibraryReference",
      "replaceV2SlotWithLibraryEntity",
      "removeV2SlotReference",
      "loadV2SlotVersions",
      "defaultV2SlotForCurrentNode",
      "submitV2SlotMicroPrompt",
      "flushV2SlotDrafts",
      "submitV2LocalSlotPrompt",
      "submitV2StoryboardPrompt",
      "runSelectedV2Slot",
      "pollV2ProviderTask",
      "selectV2SlotVersion",
      "discardV2WorkingVersion",
      "deleteV2SelectedSlotAsset",
      "attachV2Reference",
      "removeV2Reference",
      "confirmV2ShotSummary",
      "createV2FinalTimelineClip",
      "deleteV2FinalTimelineClip",
      "createV2FreeNode",
      "generateV2FreeNode",
      "absorbV2FreeNode",
      "deleteV2FreeNode",
    ]);
  });
});

describe("V2 slot prompt flush", () => {
  it("persists dirty prompts, reconciles, cleans the draft, and reports status in order", async () => {
    const { args, events, v2SlotMicroEdit } = createHarness();
    v2SlotMicroEdit.state.draftsBySlotId["slot-1"] = draft({
      prompt: "Updated prompt",
      dirty: true,
      promptDirty: true,
    });
    vi.spyOn(v2Api, "updateSlotPrompt").mockImplementation(async () => {
      events.push("update-prompt");
      return workflow([{ ...slot, slot_prompt: "Updated prompt" }]);
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.flushV2SlotDrafts();
    });

    expect(v2Api.updateSlotPrompt).toHaveBeenCalledWith("workflow-1", "slot-1", {
      slot_prompt: "Updated prompt",
      negative_prompt: "Original negative",
    });
    expect(events).toEqual([
      "status:Saving 1 V2 slot draft before run...",
      "submitting:slot-1:true:",
      "update-prompt",
      "apply",
      "clean:slot-1",
      "submitting:slot-1:false:",
      "status:V2 slot drafts saved",
    ]);
  });

  it("propagates the original error after recording it and clearing submission state", async () => {
    const error = new Error("workflow precondition failed");
    const { args, events, v2SlotMicroEdit } = createHarness();
    v2SlotMicroEdit.state.draftsBySlotId["slot-1"] = draft({
      prompt: "Updated prompt",
      dirty: true,
      promptDirty: true,
    });
    vi.spyOn(v2Api, "updateSlotPrompt").mockRejectedValue(error);
    const { result } = renderHook(() => useV2SlotOperations(args));

    let thrown: unknown;
    await act(async () => {
      try {
        await result.current.actions.flushV2SlotDrafts();
      } catch (caught) {
        thrown = caught;
      }
    });

    expect(thrown).toBe(error);
    expect(events).toEqual([
      "status:Saving 1 V2 slot draft before run...",
      "submitting:slot-1:true:",
      "submitting:slot-1:false:workflow precondition failed",
      "status:workflow precondition failed",
    ]);
  });

  it.each([412, 428])("preserves real ETag precondition behavior for HTTP %s", async (status) => {
    const { args, setStatus } = createHarness();
    v2EtagStore.set("workflow", "workflow-1", "\"state-1\"");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: { message: `precondition ${status}` },
      }), {
        status,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(workflow()), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          ETag: "\"state-2\"",
        },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useV2SlotOperations(args));

    let response: Awaited<ReturnType<typeof result.current.actions.saveV2SlotPrompt>>;
    await act(async () => {
      response = await result.current.actions.saveV2SlotPrompt(
        "slot-1",
        "Updated prompt",
        "Updated negative",
      );
    });

    expect(response!).toEqual({ ok: false });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstRequest = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(firstRequest[0]).toContain("/workflows/workflow-1/slots/slot-1/prompt");
    expect(firstRequest[1].method).toBe("PATCH");
    expect(new Headers(firstRequest[1].headers).get("If-Match")).toBe("\"state-1\"");
    expect((fetchMock.mock.calls[1] as [string, RequestInit])[1].method).toBeUndefined();
    expect(setStatus).toHaveBeenLastCalledWith(`precondition ${status}`);
    expect(v2AuthoringConflictStore.current()?.target).toEqual({
      resource: "workflow",
      id: "workflow-1",
    });
  });
});

describe("V2 slot reference operations", () => {
  it("deduplicates prompt references without changing their public attachment mapping", () => {
    const { args, v2SlotMicroEdit } = createHarness();
    const { result } = renderHook(() => useV2SlotOperations(args));

    act(() => {
      result.current.actions.syncV2SlotPromptReferences("slot-1", {
        asset_references: [
          {
            reference_source: "asset_library",
            entity_id: "entity-1",
            asset_id: "asset-1",
            role: "product",
          },
          {
            reference_source: "asset_library",
            entity_id: "entity-1",
            asset_id: "asset-1",
            role: "product",
          },
          {
            reference_source: "uploaded_asset",
            asset_id: "asset-2",
            role: "style",
          },
        ],
      });
    });

    expect(v2SlotMicroEdit.addAttachment).toHaveBeenCalledTimes(2);
    expect(v2SlotMicroEdit.addAttachment).toHaveBeenNthCalledWith(1, "slot-1", {
      id: "library:entity-1:asset-1",
      source: "asset_library",
      library_entity_id: "entity-1",
      library_asset_id: "asset-1",
      semantic_type: "product",
      status: "draft",
    });
    expect(v2SlotMicroEdit.addAttachment).toHaveBeenNthCalledWith(2, "slot-1", {
      id: "uploaded_asset:asset-2",
      source: "reference_asset",
      source_asset_id: "asset-2",
      semantic_type: "style",
      status: "registered",
    });
  });

  it("reconciles generic attach/remove responses before reporting status", async () => {
    const { args, events } = createHarness();
    vi.spyOn(v2Api, "attachReference").mockImplementation(async () => {
      events.push("attach");
      return { workflow: workflow(), assets: [], relation: null };
    });
    vi.spyOn(v2Api, "removeReference").mockImplementation(async () => {
      events.push("remove");
      return { workflow: workflow(), assets: [] };
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.attachV2Reference({
        target_type: "slot",
        target_id: "slot-1",
        source_asset_id: "asset-1",
        reference_kind: "explicit",
      });
      await result.current.actions.removeV2Reference("relation-1");
    });

    expect(events).toEqual([
      "attach",
      "apply",
      "status:V2 reference attached",
      "remove",
      "apply",
      "status:V2 reference removed",
    ]);
  });

  it("raises submission state before adding uploaded reference drafts", async () => {
    const { args, events, v2SlotMicroEdit } = createHarness();
    vi.mocked(v2SlotMicroEdit.addAttachment).mockImplementation(() => {
      events.push("add-attachment");
    });
    vi.spyOn(v2Api, "uploadSlotReferenceAsset").mockImplementation(async () => {
      events.push("upload");
      throw new Error("upload failed");
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.uploadV2SlotReference("slot-1", [
        new File(["image"], "reference.png", { type: "image/png" }),
      ]);
    });

    expect(events.slice(0, 3)).toEqual([
      "submitting:slot-1:true:",
      "add-attachment",
      "upload",
    ]);
    expect(events.slice(-2)).toEqual([
      "submitting:slot-1:false:upload failed",
      "status:upload failed",
    ]);
    expect(v2SlotMicroEdit.updateAttachment).toHaveBeenCalledWith(
      "slot-1",
      expect.any(String),
      { status: "failed", error: "upload failed" },
    );
  });
});

describe("V2 slot generation and versions", () => {
  it("regenerates after prompt persistence and preserves refresh, snapshot, history, cleanup ordering", async () => {
    const { args, events, v2SlotMicroEdit } = createHarness();
    v2SlotMicroEdit.state.draftsBySlotId["slot-1"] = draft({
      prompt: "Updated prompt",
      dirty: true,
      promptDirty: true,
    });
    vi.spyOn(v2Api, "updateSlotPrompt").mockImplementation(async () => {
      events.push("update-prompt");
      return workflow([{ ...slot, slot_prompt: "Updated prompt" }]);
    });
    vi.spyOn(v2Api, "regenerateSlot").mockImplementation(async () => {
      events.push("regenerate");
      return { workflow: workflow([{ ...slot, slot_prompt: "Updated prompt" }]) };
    });
    vi.spyOn(v2Api, "slotVersions").mockImplementation(async () => {
      events.push("versions");
      return { slot_id: "slot-1", versions: [] };
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.submitV2SlotMicroPrompt("slot-1");
    });

    expect(v2Api.regenerateSlot).toHaveBeenCalledWith("workflow-1", "slot-1");
    expect(events).toEqual([
      "submitting:slot-1:true:",
      "status:Generating working candidate for product_image...",
      "update-prompt",
      "apply",
      "regenerate",
      "apply",
      "refresh-assets",
      "snapshot",
      "versions",
      "clean:slot-1",
      "status:product_image working candidate generated",
      "submitting:slot-1:false:",
    ]);
  });

  it("selects concrete asset/version identities before workflow refresh and history reload", async () => {
    const asset = normalizeAssetVersionV2({
      asset_id: "asset-1",
      version_id: "version-1",
      media_type: "image",
      source_type: "generated",
      semantic_type: "product_image",
      status: "completed",
    });
    const { args, events } = createHarness({
      v2SlotVersionsById: {
        "slot-1": { slot_id: "slot-1", versions: [asset] },
      },
    });
    vi.spyOn(v2Api, "selectSlotVersion").mockImplementation(async () => {
      events.push("select-version");
      return {};
    });
    vi.spyOn(v2Api, "slotVersions").mockImplementation(async () => {
      events.push("versions");
      return { slot_id: "slot-1", versions: [asset] };
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.selectV2SlotVersion("slot-1", "version-1");
    });

    expect(v2Api.selectSlotVersion).toHaveBeenCalledWith("workflow-1", "slot-1", {
      asset_id: "asset-1",
      version_id: "version-1",
      source_action: "slot_version_picker",
    });
    expect(events).toEqual([
      "select-version",
      "refresh-workflow",
      "snapshot",
      "versions",
      "status:slot-1 selected version updated",
    ]);
  });

  it("reconciles working-version discard before history and does not snapshot implicitly", async () => {
    const { args, events } = createHarness();
    vi.spyOn(v2Api, "discardWorkingVersion").mockImplementation(async () => {
      events.push("discard");
      return workflow();
    });
    vi.spyOn(v2Api, "slotVersions").mockImplementation(async () => {
      events.push("versions");
      return { slot_id: "slot-1", versions: [] };
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.discardV2WorkingVersion("slot-1");
    });

    expect(events).toEqual([
      "discard",
      "apply",
      "versions",
      "status:slot-1 working version discarded",
    ]);
  });

  it("reports provider task status before refreshing workflow and snapshot", async () => {
    const { args, events } = createHarness();
    vi.spyOn(v2Api, "pollProviderTask").mockImplementation(async () => {
      events.push("poll");
      return { status: "completed" } as Awaited<
        ReturnType<typeof v2Api.pollProviderTask>
      >;
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.pollV2ProviderTask("task-1");
    });

    expect(events).toEqual([
      "poll",
      "status:Provider task completed",
      "refresh-workflow",
      "snapshot",
    ]);
  });

  it("suppresses provider polling errors after workflow identity changes", async () => {
    const { args, setStatus } = createHarness();
    vi.spyOn(v2Api, "pollProviderTask").mockImplementation(async () => {
      args.activeWorkflowIdRef.current = "workflow-2";
      throw new Error("old workflow poll failed");
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.pollV2ProviderTask("task-1");
    });

    expect(setStatus).not.toHaveBeenCalledWith("old workflow poll failed");
  });
});

describe("V2 storyboard operations", () => {
  it("confirms the current description draft and applies it before success status", async () => {
    const { args, events } = createHarness({
      dynamicItemPromptDrafts: { "shot-item-1": "Edited description" },
    });
    vi.spyOn(v2Api, "confirmShotSummary").mockImplementation(async () => {
      events.push("confirm");
      return workflow();
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.confirmV2ShotSummary(storyboardItem);
    });

    expect(v2Api.confirmShotSummary).toHaveBeenCalledWith(
      "workflow-1",
      "shot-1",
      "Edited description",
    );
    expect(events).toEqual([
      "confirm",
      "apply",
      "status:Shot one summary confirmed",
    ]);
  });

  it("regenerates a description after confirmation and always clears item saving state", async () => {
    const { args, events } = createHarness();
    const saving = args.setDynamicItemPromptSavingById as ReturnType<typeof vi.fn>;
    vi.spyOn(v2Api, "confirmShotSummary").mockImplementation(async () => {
      events.push("confirm");
      return workflow();
    });
    vi.spyOn(v2Api, "generateItem").mockImplementation(async () => {
      events.push("generate-item");
      return { workflow: workflow() };
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.submitV2StoryboardPrompt(
        storyboardItem,
        "  New description  ",
      );
    });

    expect(v2Api.confirmShotSummary).toHaveBeenCalledWith(
      "workflow-1",
      "shot-1",
      "New description",
    );
    expect(v2Api.generateItem).toHaveBeenCalledWith(
      "workflow-1",
      "shot-item-1",
      { prompt_scope: "auto" },
    );
    expect(events).toEqual([
      "status:Regenerating Shot one...",
      "confirm",
      "apply",
      "generate-item",
      "apply",
      "refresh-assets",
      "snapshot",
      "status:Shot one regenerated",
    ]);
    expect(saving).toHaveBeenCalledTimes(2);
    expect(saving.mock.calls.map(([updater]) => updater({}))).toEqual([
      { "shot-item-1": true },
      { "shot-item-1": false },
    ]);
  });
});

describe("V2 free-node operations", () => {
  it("preserves create, generate, absorb, and delete API contracts and status ordering", async () => {
    const { args, events } = createHarness();
    vi.spyOn(v2Api, "createFreeNode").mockImplementation(async () => {
      events.push("create");
      return workflow();
    });
    vi.spyOn(v2Api, "generateFreeNode").mockImplementation(async () => {
      events.push("generate");
      return { workflow: workflow() };
    });
    vi.spyOn(v2Api, "absorbFreeNode").mockImplementation(async () => {
      events.push("absorb");
      return { workflow: workflow(), relations: [{ relation_id: "relation-1" }] };
    });
    vi.spyOn(v2Api, "deleteFreeNode").mockImplementation(async () => {
      events.push("delete");
      return workflow();
    });
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.createV2FreeNode();
      await result.current.actions.generateV2FreeNode("free-node-1");
      await result.current.actions.absorbV2FreeNode(
        "free-node-1",
        "asset-1",
        "product-generation",
      );
      await result.current.actions.deleteV2FreeNode("free-node-1");
    });

    expect(v2Api.createFreeNode).toHaveBeenCalledWith("workflow-1", {
      slot_prompt: "New free generation",
    });
    expect(v2Api.generateFreeNode).toHaveBeenCalledWith(
      "workflow-1",
      "free-node-1",
      { output_media_type: "image" },
    );
    expect(v2Api.absorbFreeNode).toHaveBeenCalledWith(
      "workflow-1",
      "free-node-1",
      {
        target_node_id: "product-generation",
        asset_id: "asset-1",
        absorb_role: "reference",
      },
    );
    expect(events).toEqual([
      "create",
      "apply",
      "status:V2 free generation node created",
      "generate",
      "apply",
      "snapshot",
      "status:V2 free node generated",
      "absorb",
      "apply",
      "status:V2 free asset absorbed · 1 relations",
      "delete",
      "apply",
      "status:V2 free node deleted",
    ]);
  });

  it("rejects an incompatible absorb target without calling the API", async () => {
    const { args, setStatus } = createHarness({
      selectedFreeGenerationMediaType: "audio",
    });
    const absorb = vi.spyOn(v2Api, "absorbFreeNode");
    const { result } = renderHook(() => useV2SlotOperations(args));

    await act(async () => {
      await result.current.actions.absorbV2FreeNode(
        "free-node-1",
        "asset-1",
        "product-image",
      );
    });

    expect(absorb).not.toHaveBeenCalled();
    expect(setStatus).toHaveBeenLastCalledWith(
      "Cannot absorb audio asset into product-image.",
    );
  });
});
