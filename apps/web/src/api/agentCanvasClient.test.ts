import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "./v2Client.ts";
import { v2EtagStore } from "./v2EtagStore.ts";

const emptyWorkflow = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  nodes: [],
  bindings: [],
  assets: [],
};

const draftNode = {
  node_id: "node-image-1",
  workflow_id: "workflow-1",
  node_type: "image",
  semantic_role: "product",
  role_contract_version: "ad-media-role-v1",
  title: "Product image",
  status: "draft",
  summary_prompt: "A product portrait",
  generation_prompt: "Studio product portrait",
  structured_content: {},
  model_id: null,
  parameters: {},
  prompt_context_snapshot_id: null,
  output_asset_id: null,
  video_skill_run_id: null,
  position: { x: 120, y: 80 },
  revision: 1,
  error: null,
  created_at: "2026-07-28T00:00:00Z",
  updated_at: "2026-07-28T00:00:00Z",
};

const asset = {
  asset_id: "asset-1",
  media_type: "image",
  source_type: "upload",
  display_name: "Reference",
  mime_type: "image/png",
  status: "ready",
  preview_url: "/api/v2/assets/asset-1/content",
  media_url: "/api/v2/assets/asset-1/content",
  width: 1024,
  height: 1024,
  duration_seconds: null,
  checksum: "checksum-1",
};

afterEach(() => {
  v2EtagStore.clear();
  vi.unstubAllGlobals();
});

describe("Agent Canvas client", () => {
  it("creates and reads canonical Agent Canvas workflows while retaining real ETags", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/projects")) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("create-project-key");
        expect(JSON.parse(String(init?.body))).toEqual({
          name: "Summer launch",
          description: "",
        });
        return jsonResponse(emptyWorkflow, { status: 201, etag: '"workflow-workflow-1-r1"' });
      }
      return jsonResponse(emptyWorkflow, { etag: '"workflow-workflow-1-r2"' });
    });
    vi.stubGlobal("fetch", fetchMock);

    const created = await v2Api.createAgentCanvasProject(
      { name: "Summer launch", description: "" },
      "create-project-key",
    );
    const loaded = await v2Api.agentCanvasWorkflowWithEtag("workflow-1");

    expect(created.value.canvas_model).toBe("agent_canvas_v1");
    expect(created.etag).toBe('"workflow-workflow-1-r1"');
    expect(loaded.etag).toBe('"workflow-workflow-1-r2"');
    expect(v2EtagStore.getWorkflow("workflow-1")).toBe('"workflow-workflow-1-r2"');
  });

  it("uses the shared Workflow ETag for node and binding authoring mutations", async () => {
    v2EtagStore.set("workflow", "workflow-1", '"workflow-workflow-1-r4"');
    const binding = {
      binding_id: "binding-1",
      workflow_id: "workflow-1",
      source: { kind: "node", node_id: "node-script-1" },
      target_node_id: "node-image-1",
      binding_kind: "script_context",
      required: true,
      display_order: 0,
      created_at: "2026-07-28T00:00:00Z",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      expect(headers.get("If-Match")).toBe('"workflow-workflow-1-r4"');
      if (url.endsWith("/nodes") && init?.method === "POST") {
        return jsonResponse({ workflow: { ...emptyWorkflow, revision: 5, nodes: [draftNode] }, node: draftNode }, {
          status: 201,
          etag: '"workflow-workflow-1-r5"',
        });
      }
      if (url.endsWith("/bindings") && init?.method === "POST") {
        return jsonResponse({ workflow: { ...emptyWorkflow, revision: 5, bindings: [binding] }, binding }, {
          status: 201,
          etag: '"workflow-workflow-1-r5"',
        });
      }
      return jsonResponse({ workflow: { ...emptyWorkflow, revision: 5 } }, {
        etag: '"workflow-workflow-1-r5"',
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([
      v2Api.createAgentCanvasNode("workflow-1", {
        node_type: "image",
        semantic_role: "product",
        title: "Product image",
        summary_prompt: "A product portrait",
        generation_prompt: "Studio product portrait",
        structured_content: {},
        model_id: null,
        parameters: {},
        position: { x: 120, y: 80 },
      }),
      v2Api.createAgentCanvasBinding("workflow-1", {
        source: { kind: "node", node_id: "node-script-1" },
        target_node_id: "node-image-1",
        binding_kind: "script_context",
        required: true,
        display_order: 0,
      }),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps upload, chat, run, and export operational requests free of If-Match", async () => {
    v2EtagStore.set("workflow", "workflow-1", '"workflow-workflow-1-r7"');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      expect(headers.get("If-Match")).toBeNull();
      expect(headers.get("Idempotency-Key")).toBeTruthy();
      if (url.endsWith("/assets/upload")) {
        expect(init?.body).toBeInstanceOf(FormData);
        return jsonResponse({ workflow_id: "workflow-1", asset }, { status: 201 });
      }
      if (url.endsWith("/chat/messages")) {
        return jsonResponse({
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          message_id: "message-1",
          turn_id: "turn-1",
          status: "queued",
          events_cursor: 4,
        }, { status: 202 });
      }
      if (url.endsWith("/runs")) {
        return jsonResponse({
          workflow_id: "workflow-1",
          execution_id: "execution-1",
          status: "queued",
          accepted_node_ids: ["node-image-1"],
          joined_node_ids: [],
          skipped: [],
          waiting_node_ids: [],
          events_cursor: 5,
        }, { status: 202 });
      }
      return jsonResponse({
        workflow_id: "workflow-1",
        node_id: "node-editing-1",
        export_id: "export-1",
        status: "queued",
        manifest_revision: 2,
        ready_video_node_ids: ["node-video-1"],
        skipped_inputs: [],
        bgm_node_id: null,
        events_cursor: 6,
      }, { status: 202 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const formData = new FormData();
    formData.append("file", new File(["image"], "reference.png", { type: "image/png" }));
    formData.append("metadata", JSON.stringify({ media_type: "image", title: "Reference" }));

    await v2Api.uploadAgentCanvasAsset("workflow-1", formData, "upload-key");
    await v2Api.submitAgentCanvasChatMessage("workflow-1", {
      text: "Create the campaign",
      mentioned_node_ids: [],
      mentioned_image_asset_ids: [],
      video_skill_run_id: null,
      auto_continue: false,
    }, "chat-key");
    await v2Api.runAgentCanvas("workflow-1", {
      scope: "selected_nodes",
      node_ids: ["node-image-1"],
      retry_failed: false,
      source_action: "node_run",
    }, "run-key");
    await v2Api.exportAgentCanvasEditingNode("workflow-1", "node-editing-1", {
      expected_manifest_revision: 2,
      availability_policy: "use_ready_inputs",
    }, "export-key");

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

function jsonResponse(
  payload: unknown,
  options: { status?: number; etag?: string } = {},
) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (options.etag) headers.set("ETag", options.etag);
  return new Response(JSON.stringify(payload), {
    status: options.status ?? 200,
    headers,
  });
}
