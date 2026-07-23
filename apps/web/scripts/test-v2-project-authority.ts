import assert from "node:assert/strict";

import { v2Api, v2AuthoringPreconditionTarget } from "../src/api/v2Client.ts";
import { v2EtagStore } from "../src/api/v2EtagStore.ts";
import { v2AuthoringConflictStore } from "../src/api/v2AuthoringConflictStore.ts";
import {
  createInitialSlotMicroEditState,
  discardSlotMicroEditDraft,
  openSlotMicroEdit,
  rebaseSlotMicroEditDraft,
  updateSlotMicroEditPrompt,
} from "../src/features/workflow/v2/slots/useSlotMicroEdit.ts";
import {
  normalizeProjectV2ListResponse,
  normalizePersistedWorkflowV2,
  normalizeWorkflowRevisionPage,
} from "../src/api/v2Normalizers.ts";
import {
  projectSummaryToListItem,
  projectTrashClearsActiveWorkflow,
  loadAllBackendProjectPages,
  shouldPersistMessagesAsLocalDraft,
  shouldPersistWorkflowAsLocalDraft,
} from "../src/projects/v2ProjectAuthority.ts";
import {
  advanceWorkflowRevisionScope,
  canStartWorkflowRevisionHistoryMutation,
  getWorkflowRevisionDisplayState,
  isWorkflowRevisionRequestCurrent,
  mergeRevisionHistoryPage,
  reconcileRefreshedRevisionHistory,
  reconcileRestoredRevisionHistory,
  resetWorkflowRevisionBusyState,
  revisionActionLabel,
  revisionCanBeRestored,
  selectWorkflowRevision,
  shouldRefreshWorkflowRevisionHistory,
} from "../src/projects/v2RevisionHistory.ts";
import { shouldCloseReferencePickerAfterAuthoringResolution } from "../src/features/workflow/v2/slots/v2AssetReferencePickerConflict.ts";
import { shouldRefreshScreenplayAfterAuthoringResolution } from "../src/features/workflow/page/useWorkflowPageScreenplay.tsx";
import {
  createV2AuthoringRuntimeEventPolicy,
  createWorkflowRevisionRefreshCoalescer,
  shouldApplyRuntimeWorkflowRead,
  shouldApplyWorkflowRevisionRead,
} from "../src/features/workflow/runtime/v2AuthoringRuntimeEventPolicy.ts";
import { resolveV2ProjectCover } from "../src/projects/v2ProjectCover.ts";

const coverAssets = [
  {
    asset_id: "asset_character",
    version_id: "version_character",
    media_type: "image" as const,
    source_type: "generated" as const,
    semantic_type: "character_portrait",
    node_id: "character-generator",
    public_url: "/media/character.png",
    state: "selected",
  },
  {
    asset_id: "asset_product",
    version_id: "version_product",
    media_type: "image" as const,
    source_type: "generated" as const,
    semantic_type: "product_hero",
    node_id: "product-generator",
    public_url: "/media/product.png",
    state: "selected",
  },
  {
    asset_id: "asset_storyboard",
    version_id: "version_storyboard",
    media_type: "video" as const,
    source_type: "generated" as const,
    semantic_type: "storyboard_shot",
    node_id: "storyboard",
    public_url: "/media/storyboard.mp4",
    thumbnail_path: "/media/storyboard.jpg",
    state: "selected",
  },
  {
    asset_id: "asset_final",
    version_id: "version_final",
    media_type: "video" as const,
    source_type: "generated" as const,
    semantic_type: "final_composition",
    node_id: "final-composition",
    public_url: "/media/final.mp4",
    thumbnail_path: "/media/final.jpg",
    state: "selected",
  },
  {
    asset_id: "asset_reference",
    version_id: "version_reference",
    media_type: "image" as const,
    source_type: "generated" as const,
    semantic_type: "final_composition",
    node_id: "final-composition",
    public_url: "/media/reference.png",
    state: "reference",
  },
];

assert.deepEqual(
  resolveV2ProjectCover("asset_product", coverAssets),
  {
    assetId: "asset_product",
    versionId: "version_product",
    mediaType: "image",
    mediaPath: "/media/product.png?v=version_product",
    posterPath: null,
  },
  "the backend-selected cover asset must win over fallback source priority",
);
assert.equal(
  resolveV2ProjectCover(null, coverAssets)?.assetId,
  "asset_final",
  "final composition must be the first fallback cover",
);
assert.equal(
  resolveV2ProjectCover(null, [coverAssets[4]!, coverAssets[1]!])?.assetId,
  "asset_product",
  "reference and non-current assets must never become project covers",
);
assert.deepEqual(
  resolveV2ProjectCover("asset_freeform", [
    {
      asset_id: "asset_freeform",
      version_id: "version_freeform",
      media_type: "image",
      source_type: "generated",
      semantic_type: "freeform_generation",
      node_id: "freeform-node",
      public_url: "/media/freeform.png",
      thumbnail_path: "/media/freeform-thumb.png",
      state: "selected",
    },
    coverAssets[3]!,
  ]),
  {
    assetId: "asset_freeform",
    versionId: "version_freeform",
    mediaType: "image",
    mediaPath: "/media/freeform.png?v=version_freeform",
    posterPath: null,
  },
  "the explicitly selected cover must support any ready image asset and use its original media URL",
);

const authoringRuntimePolicy = createV2AuthoringRuntimeEventPolicy([
  { event_type: "execution_completed", workflow_id: "wf_1", seq: 1 },
  { event_type: "workflow_revision_created", workflow_id: "wf_1", seq: 2 },
  { event_type: "execution_result_revision_deferred", workflow_id: "wf_1", seq: 3, slot_id: "slot_1" },
]);
assert.equal(authoringRuntimePolicy.shouldRefreshAuthoringWorkflow, true, "a revision-created event must request the authoritative Workflow read");
assert.equal(authoringRuntimePolicy.shouldRefreshDeferredCandidates, true, "a deferred execution result must refresh candidates without authoring replacement");
assert.deepEqual(authoringRuntimePolicy.deferredCandidateSlotIds, ["slot_1"]);
assert.equal(authoringRuntimePolicy.candidateStatus, "New candidate results are available.");
assert.deepEqual(authoringRuntimePolicy.ordinaryRuntimeEvents.map((event) => event.event_type), ["execution_completed"]);

const ordinaryRuntimePolicy = createV2AuthoringRuntimeEventPolicy([
  { event_type: "execution_completed", workflow_id: "wf_1", seq: 4 },
]);
assert.equal(ordinaryRuntimePolicy.shouldRefreshAuthoringWorkflow, false, "ordinary runtime events must not read the authoring Workflow");
assert.equal(ordinaryRuntimePolicy.shouldRefreshDeferredCandidates, false);
assert.equal(ordinaryRuntimePolicy.candidateStatus, null);

const isolatedDeferredRuntimePolicy = createV2AuthoringRuntimeEventPolicy([{
  event_type: "execution_result_revision_deferred",
  workflow_id: "wf_1",
  seq: 5,
  node_id: "node_1",
  slot_id: "slot_1",
  payload: {
    provider_task_id: "task_1",
    refresh: ["workflow", "runtime", "assets", "slot_versions", "resolved_inputs"],
  },
}]);
assert.deepEqual(
  isolatedDeferredRuntimePolicy.ordinaryRuntimeEvents,
  [],
  "deferred execution results must not enter graph, provider-task, or resolved-input event paths",
);
assert.deepEqual(isolatedDeferredRuntimePolicy.deferredCandidateSlotIds, ["slot_1"]);

const synchronizationSlotVersionPolicy = createV2AuthoringRuntimeEventPolicy([{
  event_type: "linked_context_updated",
  workflow_id: "wf_1",
  seq: 6,
  slot_id: "slot_sync",
  payload: { refresh: ["slot_versions"] },
}]);
assert.deepEqual(
  synchronizationSlotVersionPolicy.ordinaryRuntimeEvents.map((event) => event.slot_id),
  ["slot_sync"],
  "synchronization events must remain eligible for their existing targeted slot-version refresh",
);
assert.equal(
  synchronizationSlotVersionPolicy.shouldRefreshSynchronizationWorkflow,
  true,
  "synchronization events must request a runtime-owned graph refresh",
);
assert.equal(
  synchronizationSlotVersionPolicy.shouldRefreshRuntimeWorkflow,
  true,
  "synchronization workflow reads must use the runtime-owned refresh path",
);

for (const event of [
  { event_type: "graph_updated", workflow_id: "wf_1", seq: 7 },
  { event_type: "workflow_updated", workflow_id: "wf_1", seq: 8 },
  {
    event_type: "execution_completed",
    workflow_id: "wf_1",
    seq: 9,
    payload: { refresh: ["workflow"] },
  },
]) {
  assert.equal(
    createV2AuthoringRuntimeEventPolicy([event]).shouldRefreshRuntimeWorkflow,
    true,
    `${event.event_type} must request a non-capturing runtime Workflow read`,
  );
}
assert.equal(
  createV2AuthoringRuntimeEventPolicy([{
    event_type: "execution_completed",
    workflow_id: "wf_1",
    seq: 10,
  }]).shouldRefreshRuntimeWorkflow,
  false,
  "ordinary runtime events without a Workflow refresh signal must not read the Workflow",
);

assert.equal(
  shouldApplyRuntimeWorkflowRead(
    { workflow_id: "wf_1", state_version: 8, semantic_revision_no: 6 },
    { workflow_id: "wf_1", state_version: 8, semantic_revision_no: 6 },
  ),
  true,
  "the current workflow revision remains safe to apply",
);
assert.equal(
  shouldApplyRuntimeWorkflowRead(
    { workflow_id: "wf_1", state_version: 7, semantic_revision_no: 6 },
    { workflow_id: "wf_1", state_version: 8, semantic_revision_no: 6 },
  ),
  false,
  "a delayed runtime read must not replace a newer active state version",
);
assert.equal(
  shouldApplyRuntimeWorkflowRead(
    { workflow_id: "wf_1", state_version: 9, semantic_revision_no: 5 },
    { workflow_id: "wf_1", state_version: 8, semantic_revision_no: 6 },
  ),
  false,
  "a delayed runtime read must not replace a newer active semantic revision",
);
assert.equal(
  shouldApplyRuntimeWorkflowRead(
    { workflow_id: "wf_2", state_version: 9, semantic_revision_no: 7 },
    { workflow_id: "wf_1", state_version: 8, semantic_revision_no: 6 },
  ),
  false,
  "a runtime read from another workflow must never apply",
);

const revisionReadCandidate = {
  workflow_id: "wf_1",
  state_version: 9,
  semantic_revision_no: 7,
};
const revisionReadCurrent = {
  workflow_id: "wf_1",
  state_version: 8,
  semantic_revision_no: 6,
};
assert.equal(
  shouldApplyWorkflowRevisionRead(revisionReadCandidate, revisionReadCurrent, {
    requestedWorkflowId: "wf_1",
    activeWorkflowId: "wf_1",
    baselineEtag: '"workflow-wf_1-v8"',
    currentEtag: '"workflow-wf_1-v8"',
  }),
  true,
  "a current revision read with an unchanged authoring baseline may apply",
);
assert.equal(
  shouldApplyWorkflowRevisionRead(revisionReadCandidate, revisionReadCurrent, {
    requestedWorkflowId: "wf_1",
    activeWorkflowId: "wf_2",
    baselineEtag: '"workflow-wf_1-v8"',
    currentEtag: '"workflow-wf_1-v8"',
  }),
  false,
  "a revision read must not apply after the active workflow changes",
);
assert.equal(
  shouldApplyWorkflowRevisionRead(revisionReadCandidate, revisionReadCurrent, {
    requestedWorkflowId: "wf_1",
    activeWorkflowId: "wf_1",
    baselineEtag: '"workflow-wf_1-v8"',
    currentEtag: '"workflow-wf_1-v9"',
  }),
  false,
  "a newer semantic operation must invalidate an in-flight revision read",
);
assert.equal(
  shouldApplyWorkflowRevisionRead(
    { ...revisionReadCandidate, semantic_revision_no: 5 },
    revisionReadCurrent,
    {
      requestedWorkflowId: "wf_1",
      activeWorkflowId: "wf_1",
      baselineEtag: '"workflow-wf_1-v8"',
      currentEtag: '"workflow-wf_1-v8"',
    },
  ),
  false,
  "an older semantic revision must remain ineligible even when the ETag baseline is unchanged",
);

const pendingWorkflowRefreshes: Array<{ workflowId: string; resolve: () => void }> = [];
const workflowRefreshCoalescer = createWorkflowRevisionRefreshCoalescer((workflowId) =>
  new Promise<void>((resolve) => {
    pendingWorkflowRefreshes.push({ workflowId, resolve });
  }),
);
const firstWorkflowRefresh = workflowRefreshCoalescer.request("wf_1");
const trailingWorkflowRefresh = workflowRefreshCoalescer.request("wf_1");
const switchedWorkflowRefresh = workflowRefreshCoalescer.request("wf_2");
assert.deepEqual(
  pendingWorkflowRefreshes.map((refresh) => refresh.workflowId),
  ["wf_1", "wf_2"],
  "a switched active workflow must retain its own refresh while another workflow read is in flight",
);
pendingWorkflowRefreshes[0]!.resolve();
await new Promise<void>((resolve) => setImmediate(resolve));
assert.deepEqual(
  pendingWorkflowRefreshes.map((refresh) => refresh.workflowId),
  ["wf_1", "wf_2", "wf_1"],
  "an event received during an in-flight read must trigger one trailing refresh for that workflow",
);
pendingWorkflowRefreshes[1]!.resolve();
pendingWorkflowRefreshes[2]!.resolve();
await Promise.all([firstWorkflowRefresh, trailingWorkflowRefresh, switchedWorkflowRefresh]);

const projects = normalizeProjectV2ListResponse({
  items: [{
    project_id: "proj_1",
    workflow_id: "wf_1",
    name: "Campaign",
    status: "active",
    is_favorite: true,
    cover_asset_id: "asset_cover",
    project_version: 3,
    updated_at: "2026-07-22T00:00:00Z",
  }],
  next_cursor: "next",
});
assert.equal(projects.items[0]?.project_version, 3);
assert.equal(projects.items[0]?.is_favorite, true);
assert.equal(projects.next_cursor, "next");
assert.throws(
  () => normalizeProjectV2ListResponse({ items: [{ workflow_id: "wf_1", name: "Campaign", status: "active", is_favorite: false, project_version: 1, updated_at: "2026-07-22T00:00:00Z" }], next_cursor: null }),
  /invalid_v2_project_payload/,
);
assert.deepEqual(projectSummaryToListItem(projects.items[0]!), {
  key: "proj_1",
  source: "saved",
  projectId: "proj_1",
  name: "Campaign",
  updatedAt: "2026-07-22T00:00:00Z",
  favorite: true,
  coverAssetId: "asset_cover",
});
assert.equal(shouldPersistWorkflowAsLocalDraft({ project_id: "proj_1" }), false);
assert.equal(shouldPersistWorkflowAsLocalDraft({}), true);
assert.equal(shouldPersistMessagesAsLocalDraft({ project_id: "proj_1" }), false);
assert.equal(shouldPersistMessagesAsLocalDraft(null), true);
assert.equal(projectTrashClearsActiveWorkflow("proj_1", "proj_1"), true);
assert.equal(projectTrashClearsActiveWorkflow("proj_1", "proj_2"), false);

const requestedProjectCursors: Array<string | null | undefined> = [];
const paginatedProjects = await loadAllBackendProjectPages(async (cursor) => {
  requestedProjectCursors.push(cursor);
  return cursor === "cursor_2"
    ? normalizeProjectV2ListResponse({ items: [{
      project_id: "proj_2",
      workflow_id: "wf_2",
      name: "Second campaign",
      status: "active",
      is_favorite: false,
      cover_asset_id: null,
      project_version: 1,
      updated_at: "2026-07-22T00:00:00Z",
    }], next_cursor: null })
    : normalizeProjectV2ListResponse({ items: [{
      project_id: "proj_1",
      workflow_id: "wf_1",
      name: "Campaign",
      status: "active",
      is_favorite: true,
      cover_asset_id: "asset_cover",
      project_version: 3,
      updated_at: "2026-07-22T00:00:00Z",
    }], next_cursor: "cursor_2" });
});
assert.deepEqual(requestedProjectCursors, [undefined, "cursor_2"]);
assert.deepEqual(paginatedProjects.map((project) => project.project_id), ["proj_1", "proj_2"]);
assert.deepEqual(v2AuthoringPreconditionTarget("/workflows/wf_1/script/confirm", "POST"), { resource: "workflow", id: "wf_1" });
assert.deepEqual(v2AuthoringPreconditionTarget("/workflows/wf_1/final-composition/timeline", "PATCH"), { resource: "workflow", id: "wf_1" });
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/slots/slot_1/working-version/discard", "POST"), null);
assert.deepEqual(v2AuthoringPreconditionTarget("/workflows/wf_1/slots/slot_1/reference-assets/upload", "POST"), { resource: "workflow", id: "wf_1" });
assert.deepEqual(v2AuthoringPreconditionTarget("/workflows/wf_1/chat-actions", "POST"), { resource: "workflow", id: "wf_1" });
assert.deepEqual(v2AuthoringPreconditionTarget("/projects/proj_1/restore", "POST"), { resource: "project", id: "proj_1" });
assert.equal(v2AuthoringPreconditionTarget("/workflows/plan-from-prompt", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/plan-from-chat", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/run", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/run?wait=false", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/slots/slot_1/generate", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/runtime", "GET"), null);

const screenplayResolution = {
  target: { resource: "workflow" as const, id: "wf_1" },
  operationPath: "/workflows/wf_1/script/confirm",
  action: "retry" as const,
};
assert.equal(shouldRefreshScreenplayAfterAuthoringResolution(screenplayResolution, "wf_1"), true);
assert.equal(shouldRefreshScreenplayAfterAuthoringResolution({ ...screenplayResolution, action: "discard" }, "wf_1"), false);
assert.equal(shouldCloseReferencePickerAfterAuthoringResolution({
  target: { resource: "workflow", id: "wf_1" },
  operationPath: "/workflows/wf_1/slots/slot_1/reference-selections",
  action: "discard",
}, "wf_1", "slot_1"), true);
assert.equal(shouldCloseReferencePickerAfterAuthoringResolution({
  target: { resource: "workflow", id: "wf_1" },
  operationPath: "/workflows/wf_1/slots/slot_1/reference-selections",
  action: "retry",
}, "wf_1", "slot_1"), true);

for (const path of [
  "/workflows/wf_1/script/versions/script_2/select",
  "/workflows/wf_1/revisions/2/restore",
  "/workflows/wf_1/slots/slot_1/reference-selections",
  "/workflows/wf_1/slots/slot_1/select-version",
  "/workflows/wf_1/slots/slot_1/references",
  "/workflows/wf_1/assets/register-reference",
  "/workflows/wf_1/assets/register-library-reference",
  "/workflows/wf_1/assets/asset_1/absorb",
  "/workflows/wf_1/storyboard/shots/shot_1/detail-prompts",
  "/workflows/wf_1/storyboard/shots/shot_1/primary-scene",
  "/workflows/wf_1/slots/slot_1/selected-asset",
  "/workflows/wf_1/references/reference_1",
  "/workflows/wf_1/free-nodes",
  "/workflows/wf_1/free-nodes/node_1/absorb",
  "/workflows/wf_1/free-nodes/node_1",
  "/workflows/wf_1/final-composition/timeline/clips",
  "/workflows/wf_1/final-composition/timeline/sources",
]) {
  assert.deepEqual(v2AuthoringPreconditionTarget(path, path.includes("detail-prompts") || path.includes("primary-scene") ? "PATCH" : path.endsWith("reference_1") || path.endsWith("node_1") ? "DELETE" : "POST"), { resource: "workflow", id: "wf_1" }, `${path} must use the shared workflow ETag`);
}

for (const path of [
  "/workflows/wf_1/run",
  "/workflows/wf_1/slots/slot_1/generate",
  "/workflows/wf_1/slots/slot_1/regenerate",
  "/workflows/wf_1/items/item_1/generate",
  "/workflows/wf_1/free-nodes/node_1/generate",
  "/workflows/wf_1/provider-tasks/task_1/poll",
  "/workflows/wf_1/executions/execution_1/resume",
  "/workflows/wf_1/chat-target",
  "/workflows/wf_1/final-composition/render",
  "/workflows/wf_1/final-composition/renders/render_1/cancel",
]) {
  assert.equal(v2AuthoringPreconditionTarget(path, "POST"), null, `${path} is operational and must not send If-Match`);
}

const revisions = normalizeWorkflowRevisionPage({
  items: [{
    revision_id: "rev_2",
    workflow_id: "wf_1",
    revision_no: 2,
    state_version: 2,
    content_hash: "a".repeat(64),
    change_source: "prompt_edit",
    restored_from_revision_no: null,
    source_execution_id: null,
    created_at: "2026-07-22T00:00:00Z",
  }],
  next_cursor: null,
});
assert.equal(revisions.items[0]?.revision_no, 2);
assert.equal(revisionCanBeRestored(revisions.items[0]!, 3), true);
assert.equal(revisionCanBeRestored(revisions.items[0]!, 2), false);
assert.equal(revisionActionLabel(revisions.items[0]!), "Revision 2 · Prompt edit");
const revisionOne = { ...revisions.items[0]!, revision_id: "rev_1", revision_no: 1 };
const revisionThree = { ...revisions.items[0]!, revision_id: "rev_3", revision_no: 3 };
assert.deepEqual(
  resetWorkflowRevisionBusyState(),
  { loadingHistory: false, loadingMore: false, loadingDetail: null, restoring: null },
  "changing workflows must clear every revision request busy state before stale requests settle",
);
const firstWorkflowRevisionScope = advanceWorkflowRevisionScope({ workflowId: null, generation: 0 }, "wf_1");
const secondWorkflowRevisionScope = advanceWorkflowRevisionScope(firstWorkflowRevisionScope, "wf_2");
assert.equal(
  canStartWorkflowRevisionHistoryMutation(secondWorkflowRevisionScope, {
    workflowId: "wf_2",
    generation: secondWorkflowRevisionScope.generation,
  }),
  false,
  "an active history mutation must serialize Load more and restore refreshes for the same workflow",
);
assert.equal(
  canStartWorkflowRevisionHistoryMutation(secondWorkflowRevisionScope, {
    workflowId: "wf_1",
    generation: firstWorkflowRevisionScope.generation,
  }),
  true,
  "a stale workflow mutation must not block history work for the active workflow",
);
assert.equal(
  isWorkflowRevisionRequestCurrent(secondWorkflowRevisionScope, 2, {
    workflowId: "wf_1",
    workflowGeneration: firstWorkflowRevisionScope.generation,
    requestGeneration: 2,
  }),
  false,
  "a response started for a previous active workflow must not update the current workflow state",
);
assert.equal(
  isWorkflowRevisionRequestCurrent(secondWorkflowRevisionScope, 2, {
    workflowId: "wf_2",
    workflowGeneration: secondWorkflowRevisionScope.generation,
    requestGeneration: 1,
  }),
  false,
  "a superseded request for the active workflow must not apply after a newer request starts",
);
assert.equal(
  isWorkflowRevisionRequestCurrent(secondWorkflowRevisionScope, 2, {
    workflowId: "wf_2",
    workflowGeneration: secondWorkflowRevisionScope.generation,
    requestGeneration: 2,
  }),
  true,
  "the current request for the active workflow must remain applicable",
);
const loadedRevisionHistory = {
  items: [revisions.items[0]!, revisionOne],
  nextCursor: "cursor_1",
  selectedRevisionNo: 2,
};
assert.equal(
  shouldRefreshWorkflowRevisionHistory({
    activeWorkflowId: "wf_1",
    stateWorkflowId: "wf_1",
    open: true,
    history: loadedRevisionHistory,
    semanticRevisionNo: 3,
  }),
  true,
  "an open history panel must refresh its first page when the active workflow advances to an unloaded revision",
);
assert.equal(
  shouldRefreshWorkflowRevisionHistory({
    activeWorkflowId: "wf_1",
    stateWorkflowId: "wf_1",
    open: true,
    history: { ...loadedRevisionHistory, items: [revisionThree, ...loadedRevisionHistory.items] },
    semanticRevisionNo: 3,
  }),
  false,
  "an open history panel must not reload when the authoritative revision is already present",
);
assert.equal(
  shouldRefreshWorkflowRevisionHistory({
    activeWorkflowId: "wf_1",
    stateWorkflowId: "wf_2",
    open: true,
    history: loadedRevisionHistory,
    semanticRevisionNo: 3,
  }),
  false,
  "a stale workflow history state must not refresh after an active-workflow update",
);
assert.deepEqual(
  getWorkflowRevisionDisplayState("wf_2", "wf_1", {
    open: true,
    history: loadedRevisionHistory,
    selectedRevision: { revision_no: 2 },
    error: "The previous workflow failed.",
    loadingHistory: true,
    loadingMore: true,
    loadingDetail: 2,
    restoring: 1,
  }),
  {
    open: false,
    history: { items: [], nextCursor: null, selectedRevisionNo: null },
    selectedRevision: null,
    error: null,
    loadingHistory: false,
    loadingMore: false,
    loadingDetail: null,
    restoring: null,
  },
  "a workflow switch must hide every prior-workflow revision state before the cleanup effect runs",
);
assert.deepEqual(
  mergeRevisionHistoryPage(loadedRevisionHistory, { items: [revisionThree, revisions.items[0]!], next_cursor: "cursor_2" }),
  { items: [revisionThree, revisions.items[0]!, revisionOne], nextCursor: "cursor_2", selectedRevisionNo: 2 },
  "refreshing the first page must preserve previously loaded history while deduplicating revisions",
);
assert.deepEqual(
  reconcileRefreshedRevisionHistory(
    loadedRevisionHistory,
    { items: [revisionThree, revisions.items[0]!], next_cursor: "cursor_2" },
  ),
  { items: [revisionThree, revisions.items[0]!, revisionOne], nextCursor: "cursor_1", selectedRevisionNo: 2 },
  "an automatic first-page refresh must preserve the older-page cursor and user selection",
);
assert.deepEqual(
  selectWorkflowRevision(loadedRevisionHistory, 1),
  { ...loadedRevisionHistory, selectedRevisionNo: 1 },
  "selecting a summary must retain the loaded history and identify the detail to load",
);
assert.deepEqual(
  reconcileRestoredRevisionHistory(loadedRevisionHistory, { items: [revisionThree, revisions.items[0]!], next_cursor: "cursor_2" }, revisionThree, true),
  { items: [revisionThree, revisions.items[0]!, revisionOne], nextCursor: "cursor_1", selectedRevisionNo: 3 },
  "restore refresh must retain the older-page cursor when loaded history extends past the refreshed first page",
);
assert.deepEqual(
  reconcileRestoredRevisionHistory(
    { ...loadedRevisionHistory, selectedRevisionNo: 1 },
    { items: [revisionThree, revisions.items[0]!], next_cursor: "cursor_2" },
    revisionThree,
    false,
  ),
  { items: [revisionThree, revisions.items[0]!, revisionOne], nextCursor: "cursor_1", selectedRevisionNo: 1 },
  "stale restore reconciliation must preserve a later explicit revision selection",
);
assert.throws(
  () => normalizeWorkflowRevisionPage({ items: [{ revision_id: "rev_1", workflow_id: "wf_1", revision_no: 1, state_version: 1, change_source: "create", created_at: "2026-07-22T00:00:00Z" }], next_cursor: null }),
  /invalid_v2_workflow_revision_payload/,
);
assert.equal(normalizePersistedWorkflowV2(workflowPayload()).project_id, "proj_1");
assert.throws(
  () => normalizePersistedWorkflowV2({ ...workflowPayload(), project_id: undefined }),
  /invalid_v2_persisted_workflow/,
);

const calls: Array<{ url: string; init: RequestInit }> = [];
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  calls.push({ url: String(input), init });
  return jsonResponse(
    { ...workflowPayload(), state_version: 6, semantic_revision_no: 6 },
    { ETag: '"workflow-wf_1-v6"' },
  );
}) as typeof fetch;
v2EtagStore.clear();
v2EtagStore.set("workflow", "wf_1", '"workflow-wf_1-v5"');
const nonCapturingWorkflow = await v2Api.workflowWithEtagWithoutCapture("wf_1");
assert.equal(nonCapturingWorkflow.etag, '"workflow-wf_1-v6"', "a non-capturing read must preserve the real response ETag for later validation");
assert.equal(nonCapturingWorkflow.value.state_version, 6);
assert.equal(
  v2EtagStore.getWorkflow("wf_1"),
  '"workflow-wf_1-v5"',
  "a non-capturing workflow read must not mutate the central authoring ETag",
);
await v2Api.workflowWithEtag("wf_1");
assert.equal(
  v2EtagStore.getWorkflow("wf_1"),
  '"workflow-wf_1-v6"',
  "an ordinary semantic workflow read must continue capturing the response ETag",
);

calls.length = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input);
  calls.push({ url, init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v4"' });
  }
  if (url.endsWith("/generate")) {
    return jsonResponse({ workflow: workflowPayload(), executed_slot_ids: [], provider_calls: [] });
  }
  return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v5"' });
}) as typeof fetch;

v2EtagStore.clear();
await v2Api.updateSlotPrompt("wf_1", "slot_1", { slot_prompt: "Updated" });
assert.equal(calls.length, 2);
assert.equal(calls[0]?.init.method ?? "GET", "GET");
assert.equal(new Headers(calls[1]?.init.headers).get("If-Match"), '"workflow-wf_1-v4"');
assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v5"');

calls.length = 0;
await v2Api.generateSlot("wf_1", "slot_1");
assert.equal(calls.length, 1);
assert.equal(new Headers(calls[0]?.init.headers).has("If-Match"), false);

calls.length = 0;
await v2Api.discardWorkingVersion("wf_1", "slot_1");
assert.equal(calls.length, 1);
assert.equal(new Headers(calls[0]?.init.headers).has("If-Match"), false);

calls.length = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  calls.push({ url: String(input), init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(workflowPayload());
  }
  return jsonResponse({
    workflow: workflowPayload(),
    executed_slot_ids: [],
    provider_calls: [],
  });
}) as typeof fetch;
v2EtagStore.clear();
await v2Api.runWorkflowAsync("wf_1");
assert.equal(calls.length, 2, "Global Run must proceed after a workflow read without an ETag");
assert.equal(calls[0]?.init.method ?? "GET", "GET");
assert.equal(new Headers(calls[1]?.init.headers).has("If-Match"), false, "Global Run must omit If-Match when the backend does not provide a real ETag");
assert.equal(v2EtagStore.getWorkflow("wf_1"), null, "Global Run must not synthesize or persist an ETag");

for (const status of [412, 428]) {
  calls.length = 0;
  let runAttempts = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), init });
    if ((init.method ?? "GET") === "GET") return jsonResponse(workflowPayload());
    runAttempts += 1;
    return jsonResponse(
      { detail: { code: "workflow_precondition_required", message: `Global Run precondition ${status}.` } },
      {},
      status,
    );
  }) as typeof fetch;
  v2AuthoringConflictStore.clear();
  v2EtagStore.clear();

  await assert.rejects(() => v2Api.runWorkflowAsync("wf_1"));
  assert.equal(runAttempts, 1, `Global Run without an ETag must not retry after HTTP ${status}`);
  assert.equal(calls.length, 2, `Global Run without an ETag must not refresh authoring state after HTTP ${status}`);
  assert.equal(new Headers(calls[1]?.init.headers).has("If-Match"), false);
  assert.equal(v2AuthoringConflictStore.current(), null, `Global Run without an ETag must not enter the shared conflict flow for HTTP ${status}`);
}

calls.length = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  calls.push({ url: String(input), init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v10"' });
  }
  return jsonResponse({
    workflow: workflowPayload(),
    executed_slot_ids: [],
    provider_calls: [],
  }, { ETag: '"workflow-wf_1-v11"' });
}) as typeof fetch;
v2EtagStore.clear();
await v2Api.runWorkflowAsync("wf_1");
assert.equal(calls.length, 2, "Global Run must obtain a real Workflow ETag when no current value is cached");
assert.equal(calls[0]?.init.method ?? "GET", "GET");
assert.equal(new Headers(calls[1]?.init.headers).get("If-Match"), '"workflow-wf_1-v10"');
assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v10"', "an operational run response must not replace the authoring ETag");

for (const status of [412, 428]) {
  calls.length = 0;
  let runAttempts = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), init });
    if ((init.method ?? "GET") === "GET") {
      return jsonResponse(
        { ...workflowPayload(), state_version: 21, semantic_revision_no: 21 },
        { ETag: '"workflow-wf_1-v21"' },
      );
    }
    runAttempts += 1;
    if (runAttempts === 1) {
      return jsonResponse(
        {
          detail: {
            code: status === 412 ? "workflow_state_conflict" : "workflow_precondition_required",
            message: `Global Run precondition ${status}.`,
          },
        },
        {},
        status,
      );
    }
    return jsonResponse({
      workflow: { ...workflowPayload(), state_version: 22, semantic_revision_no: 21 },
      executed_slot_ids: [],
      provider_calls: [],
    }, { ETag: '"workflow-wf_1-v22"' });
  }) as typeof fetch;
  v2AuthoringConflictStore.clear();
  v2EtagStore.set("workflow", "wf_1", '"workflow-wf_1-v20"');

  await assert.rejects(() => v2Api.runWorkflowAsync("wf_1"));
  assert.equal(runAttempts, 1, `Global Run must not silently retry after HTTP ${status}`);
  assert.equal(calls.length, 2, `Global Run HTTP ${status} must refresh the current Workflow before offering resolution`);
  assert.equal(calls[1]?.init.method ?? "GET", "GET");
  assert.deepEqual(
    v2AuthoringConflictStore.current()?.target,
    { resource: "workflow", id: "wf_1" },
    `Global Run HTTP ${status} must enter the shared workflow conflict flow`,
  );
  assert.equal(v2AuthoringConflictStore.current()?.operationPath, "/workflows/wf_1/run?wait=false");
  assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v21"');

  if (status === 412) {
    await v2AuthoringConflictStore.retry();
    assert.equal(runAttempts, 2, "Global Run must retry only after explicit conflict resolution");
    assert.equal(new Headers(calls.at(-1)?.init.headers).get("If-Match"), '"workflow-wf_1-v21"');
    assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v21"', "a retried Global Run response must remain non-capturing");
  } else {
    await v2AuthoringConflictStore.discard();
    assert.equal(runAttempts, 1, "discarding a Global Run conflict must not issue another run request");
  }
  assert.equal(v2AuthoringConflictStore.current(), null);
}

calls.length = 0;
let patchAttempts = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input);
  calls.push({ url, init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v6"' });
  }
  patchAttempts += 1;
  if (patchAttempts === 1) {
    return jsonResponse(
      { detail: { code: "workflow_state_conflict", message: "Workflow changed." } },
      {},
      412,
    );
  }
  return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v7"' });
}) as typeof fetch;
v2AuthoringConflictStore.clear();
v2EtagStore.set("workflow", "wf_1", '"workflow-wf_1-v5"');
await assert.rejects(() => v2Api.updateSlotPrompt("wf_1", "slot_1", { slot_prompt: "Keep this draft" }));
assert.equal(patchAttempts, 1, "a conflict must not silently retry");
assert.equal(calls.length, 2, "a conflict must immediately refresh the current workflow before it is shown to the user");
assert.equal(calls[1]?.init.method ?? "GET", "GET");
assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v6"');
assert.equal(v2AuthoringConflictStore.current()?.target.id, "wf_1");
await v2AuthoringConflictStore.retry();
assert.equal(patchAttempts, 2);
assert.equal(new Headers(calls.at(-1)?.init.headers).get("If-Match"), '"workflow-wf_1-v6"');
assert.equal(v2AuthoringConflictStore.current(), null);

calls.length = 0;
let preconditionAttempts = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  calls.push({ url: String(input), init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v10"' });
  }
  preconditionAttempts += 1;
  if (preconditionAttempts === 1) {
    return jsonResponse(
      { detail: { code: "workflow_precondition_required", message: "Current workflow ETag is required." } },
      {},
      428,
    );
  }
  return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v11"' });
}) as typeof fetch;
v2AuthoringConflictStore.clear();
v2EtagStore.set("workflow", "wf_1", '"workflow-wf_1-v9"');
await assert.rejects(() => v2Api.updateSlotPrompt("wf_1", "slot_1", { slot_prompt: "Retry after 428" }));
assert.equal(calls.length, 2, "HTTP 428 must fetch the current workflow and ETag before retry is offered");
assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v10"');
await v2AuthoringConflictStore.retry();
assert.equal(preconditionAttempts, 2);
assert.equal(new Headers(calls.at(-1)?.init.headers).get("If-Match"), '"workflow-wf_1-v10"');

calls.length = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  calls.push({ url: String(input), init });
  return jsonResponse(workflowPayload());
}) as typeof fetch;
v2EtagStore.clear();
await assert.rejects(
  () => v2Api.updateSlotPrompt("wf_1", "slot_1", { slot_prompt: "No synthesized ETag" }),
  /Missing backend ETag/,
);
assert.equal(calls.length, 1, "a semantic mutation must stop when the backend read does not provide a real ETag");

calls.length = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input);
  calls.push({ url, init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(workflowPayload(), { ETag: '"workflow-wf_1-v8"' });
  }
  return jsonResponse({
    workflow: workflowPayload(),
    bindings: [],
    removed_binding_id: null,
  }, { ETag: '"workflow-wf_1-v9"' });
}) as typeof fetch;
v2EtagStore.clear();
await v2Api.attachReferenceSelections("wf_1", "slot_1", {
  selections: [],
  reference_role: "visual_reference",
  use_as_prompt: true,
});
assert.equal(calls.length, 2, "reference selection must obtain a real workflow ETag through the shared store");
assert.equal(calls[0]?.init.method ?? "GET", "GET");
assert.equal(new Headers(calls[1]?.init.headers).get("If-Match"), '"workflow-wf_1-v8"');
assert.equal(v2EtagStore.getWorkflow("wf_1"), '"workflow-wf_1-v9"');

calls.length = 0;
globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input);
  calls.push({ url, init });
  if ((init.method ?? "GET") === "GET") {
    return jsonResponse(projectPayload(), { ETag: '"project-proj_1-v3"' });
  }
  if ((init.method ?? "GET") === "DELETE") {
    return new Response(null, { status: 204, headers: { ETag: '"project-proj_1-v4"' } });
  }
  return jsonResponse({ ...projectPayload(), status: "active", project_version: 5, deleted_at: null }, { ETag: '"project-proj_1-v5"' });
}) as typeof fetch;
v2EtagStore.clear();
await v2Api.trashProject("proj_1");
assert.equal(calls.length, 2, "trashing a Project must fetch its current ETag before the first lifecycle mutation");
assert.equal(new Headers(calls[1]?.init.headers).get("If-Match"), '"project-proj_1-v3"');
assert.equal(v2EtagStore.getProject("proj_1"), '"project-proj_1-v4"');

calls.length = 0;
await v2Api.restoreProject("proj_1");
assert.equal(calls.length, 1, "restore must reuse the replacement ETag returned by the soft-delete response");
assert.equal(new Headers(calls[0]?.init.headers).get("If-Match"), '"project-proj_1-v4"');
assert.equal(v2EtagStore.getProject("proj_1"), '"project-proj_1-v5"');

const slotDraftBase = slotPayload("Server prompt");
let slotDraftState = openSlotMicroEdit(createInitialSlotMicroEditState(), slotDraftBase);
slotDraftState = updateSlotMicroEditPrompt(slotDraftState, slotDraftBase.slot_id, "Keep this local prompt");
slotDraftState = rebaseSlotMicroEditDraft(slotDraftState, slotPayload("Keep this local prompt"));
assert.equal(slotDraftState.draftsBySlotId[slotDraftBase.slot_id]?.prompt, "Keep this local prompt");
assert.equal(slotDraftState.draftsBySlotId[slotDraftBase.slot_id]?.promptDirty, false, "a successful retry must reconcile the local prompt draft with the refreshed server state");
assert.equal(slotDraftState.draftsBySlotId[slotDraftBase.slot_id]?.dirty, false);

slotDraftState = updateSlotMicroEditPrompt(slotDraftState, slotDraftBase.slot_id, "Discard this local prompt");
slotDraftState = discardSlotMicroEditDraft(slotDraftState, slotPayload("Latest server prompt"));
assert.equal(slotDraftState.draftsBySlotId[slotDraftBase.slot_id]?.prompt, "Latest server prompt");
assert.equal(slotDraftState.draftsBySlotId[slotDraftBase.slot_id]?.dirty, false, "discard must replace the local Slot draft with the current backend value");

function workflowPayload() {
  return {
    workflow_id: "wf_1",
    project_id: "proj_1",
    workflow_schema_version: 2,
    state_version: 5,
    semantic_revision_no: 5,
    nodes: [],
    items: [],
    slots: [],
    asset_versions: [],
    edges: [],
  };
}

function projectPayload() {
  return {
    project_id: "proj_1",
    workflow_id: "wf_1",
    name: "Campaign",
    description: "",
    status: "trashed",
    is_favorite: false,
    cover_asset_id: null,
    project_version: 3,
    semantic_revision_no: 5,
    created_at: "2026-07-22T00:00:00Z",
    updated_at: "2026-07-22T00:00:00Z",
    deleted_at: "2026-07-22T00:00:00Z",
  };
}

function slotPayload(prompt: string) {
  return {
    slot_id: "slot_1",
    node_id: "node_1",
    item_id: "item_1",
    slot_type: "product_main_image",
    media_type: "image",
    required: true,
    status: "ready",
    user_prompt: prompt,
    negative_prompt: "",
    explicit_reference_ids: [],
  } as const;
}

function jsonResponse(payload: unknown, headers: Record<string, string> = {}, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
