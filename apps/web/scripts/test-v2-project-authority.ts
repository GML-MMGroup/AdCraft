import assert from "node:assert/strict";

import { v2Api } from "../src/api/v2Client.ts";
import { v2EtagStore } from "../src/api/v2EtagStore.ts";
import {
  normalizeProjectV2ListResponse,
  normalizeWorkflowRevisionPage,
} from "../src/api/v2Normalizers.ts";
import {
  projectSummaryToListItem,
  shouldPersistWorkflowAsLocalDraft,
} from "../src/projects/v2ProjectAuthority.ts";

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

function jsonResponse(payload: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
