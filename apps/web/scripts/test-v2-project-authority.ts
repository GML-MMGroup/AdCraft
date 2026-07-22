import assert from "node:assert/strict";

import { v2Api, v2AuthoringPreconditionTarget } from "../src/api/v2Client.ts";
import { v2EtagStore } from "../src/api/v2EtagStore.ts";
import { v2AuthoringConflictStore } from "../src/api/v2AuthoringConflictStore.ts";
import {
  normalizeProjectV2ListResponse,
  normalizeWorkflowRevisionPage,
} from "../src/api/v2Normalizers.ts";
import {
  projectSummaryToListItem,
  shouldPersistWorkflowAsLocalDraft,
} from "../src/projects/v2ProjectAuthority.ts";
import { revisionActionLabel, revisionCanBeRestored } from "../src/projects/v2RevisionHistory.ts";

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
assert.deepEqual(v2AuthoringPreconditionTarget("/workflows/wf_1/script/confirm", "POST"), { resource: "workflow", id: "wf_1" });
assert.deepEqual(v2AuthoringPreconditionTarget("/workflows/wf_1/final-composition/timeline", "PATCH"), { resource: "workflow", id: "wf_1" });
assert.deepEqual(v2AuthoringPreconditionTarget("/projects/proj_1/restore", "POST"), { resource: "project", id: "proj_1" });
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/run", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/slots/slot_1/generate", "POST"), null);
assert.equal(v2AuthoringPreconditionTarget("/workflows/wf_1/runtime", "GET"), null);

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
assert.equal(v2AuthoringConflictStore.current()?.target.id, "wf_1");
await v2AuthoringConflictStore.retry();
assert.equal(patchAttempts, 2);
assert.equal(new Headers(calls.at(-1)?.init.headers).get("If-Match"), '"workflow-wf_1-v6"');
assert.equal(v2AuthoringConflictStore.current(), null);

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

function jsonResponse(payload: unknown, headers: Record<string, string> = {}, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
