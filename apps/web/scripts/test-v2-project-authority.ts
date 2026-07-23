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
import { revisionActionLabel, revisionCanBeRestored } from "../src/projects/v2RevisionHistory.ts";
import { shouldCloseReferencePickerAfterAuthoringResolution } from "../src/features/workflow/v2/slots/v2AssetReferencePickerConflict.ts";
import { shouldRefreshScreenplayAfterAuthoringResolution } from "../src/features/workflow/page/useWorkflowPageScreenplay.tsx";

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
