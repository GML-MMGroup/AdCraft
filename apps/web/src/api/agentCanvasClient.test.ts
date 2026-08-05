import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "./v2Client.ts";
import { v2EtagStore } from "./v2EtagStore.ts";

const emptyWorkflow = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  layout_revision: 1,
  nodes: [],
  bindings: [],
  assets: [],
};

const draftNode = {
  node_id: "node-image-1",
  workflow_id: "workflow-1",
  node_type: "image",
  creative_role: "product",
  role_contract_version: "ad-media-role-v2",
  title: "Product image",
  status: "draft",
  summary_prompt: "A product portrait",
  generation_prompt: "Studio product portrait",
  structured_content: {},
  model_id: null,
  parameters: {},
  prompt_context_snapshot_id: null,
  output_asset_id: null,
  position: { x: 120, y: 80 },
  revision: 1,
  error: null,
  variation_draft: null,
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
        return jsonResponse({
          ...emptyWorkflow,
          active_style_skill_run_id: "style-skill-run-1",
          guidance_session_id: "guidance-session-1",
        }, { status: 201, etag: '"workflow-workflow-1-r1"' });
      }
      return jsonResponse(emptyWorkflow, { etag: '"workflow-workflow-1-r2"' });
    });
    vi.stubGlobal("fetch", fetchMock);

    const created = await v2Api.createAgentCanvasProject(
      { name: "Summer launch", description: "" },
      "create-project-key",
    );
    const loaded = await v2Api.agentCanvasWorkflowWithEtag("workflow-1");

    expect(created.value.active_style_skill_run_id).toBe("style-skill-run-1");
    expect(created.value.guidance_session_id).toBe("guidance-session-1");
    expect(created.etag).toBe('"workflow-workflow-1-r1"');
    expect(loaded.etag).toBe('"workflow-workflow-1-r2"');
    expect(v2EtagStore.getWorkflow("workflow-1")).toBe('"workflow-workflow-1-r2"');
  });

  it("uses the shared Workflow ETag for node and binding authoring mutations", async () => {
    v2EtagStore.set("workflow", "workflow-1", '"workflow-workflow-1-r4"');
    const binding = {
      binding_id: "binding-1",
      workflow_id: "workflow-1",
      source: { kind: "node_output", source_node_id: "node-script-1" },
      target_node_id: "node-image-1",
      input_role: "text_context",
      required: true,
      enabled: true,
      order: 0,
      label: null,
      metadata: {},
      created_at: "2026-07-28T00:00:00Z",
      updated_at: "2026-07-28T00:00:00Z",
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
        creative_role: "product",
        title: "Product image",
        summary_prompt: "A product portrait",
        generation_prompt: "Studio product portrait",
        structured_content: {},
        model_id: null,
        parameters: {},
        position: { x: 120, y: 80 },
      }),
      v2Api.createAgentCanvasBinding("workflow-1", {
        source: { kind: "node_output", source_node_id: "node-script-1" },
        target_node_id: "node-image-1",
        input_role: "text_context",
        required: true,
        enabled: true,
        order: 0,
        label: null,
        metadata: {},
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
        expect(JSON.parse(String(init?.body))).toEqual({
          text: "Create the campaign",
          mentioned_node_ids: [],
          mentioned_image_asset_ids: [],
          video_skill_run_id: null,
        });
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
          run_intent_snapshot_ids: {
            "node-image-1": "run-intent-snapshot-1",
          },
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
    }, "chat-key");
    const runAccepted = await v2Api.runAgentCanvas("workflow-1", {
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
    expect(runAccepted.run_intent_snapshot_ids).toEqual({
      "node-image-1": "run-intent-snapshot-1",
    });
  });

  it("uses semantic ETags for command actions and Ready variation authoring", async () => {
    v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:7"');
    const readyNode = {
      ...draftNode,
      status: "ready",
      output_asset_id: "asset-1",
    };
    const variationDraft = {
      source_node_id: readyNode.node_id,
      source_node_revision: readyNode.revision,
      title: "Product image variation",
      generation_prompt: "A warmer studio portrait.",
      model_id: null,
      parameters: {},
      variation_revision: 1,
      created_at: "2026-07-29T01:00:00Z",
      updated_at: "2026-07-29T01:00:00Z",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      expect(headers.get("If-Match")).toMatch(/^"workflow:workflow-1:revision:/);
      if (url.endsWith("/command-plans/plan-1/actions")) {
        expect(headers.get("Idempotency-Key")).toBe("command-key");
        expect(JSON.parse(String(init?.body))).toEqual({ action: "confirm" });
        return jsonResponse({
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          message_id: null,
          turn_id: "turn-command-1",
          status: "queued",
          events_cursor: 20,
        }, { status: 202 });
      }
      if (url.endsWith("/variation-draft") && init?.method === "PUT") {
        return jsonResponse({
          workflow_id: "workflow-1",
          workflow_revision: 8,
          node_id: readyNode.node_id,
          variation_draft: variationDraft,
        }, { etag: '"workflow:workflow-1:revision:8"' });
      }
      if (url.endsWith("/variation-draft/materialize")) {
        expect(headers.get("Idempotency-Key")).toBe("materialize-key");
        expect(JSON.parse(String(init?.body))).toEqual({ action: "create_draft" });
        return jsonResponse({
          workflow_id: "workflow-1",
          workflow_revision: 9,
          source_node_id: readyNode.node_id,
          sibling_node: {
            ...draftNode,
            node_id: "node-image-sibling",
            revision: 1,
          },
          copied_binding_ids: [],
          run: null,
          run_error: null,
          placement_hint: {
            intent: "right_sibling",
            anchor_node_id: readyNode.node_id,
            group_key: null,
          },
        }, { status: 202, etag: '"workflow:workflow-1:revision:9"' });
      }
      if (url.endsWith("/variation-draft") && init?.method === "DELETE") {
        return new Response(null, {
          status: 204,
          headers: { ETag: '"workflow:workflow-1:revision:10"' },
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await v2Api.actOnAgentCanvasCommandPlan(
      "workflow-1",
      "plan-1",
      { action: "confirm" },
      "command-key",
    );
    await v2Api.saveAgentCanvasVariationDraft("workflow-1", readyNode.node_id, {
      title: variationDraft.title,
      generation_prompt: variationDraft.generation_prompt,
      model_id: null,
      parameters: {},
    });
    await v2Api.materializeAgentCanvasVariationDraft(
      "workflow-1",
      readyNode.node_id,
      { action: "create_draft" },
      "materialize-key",
    );
    await v2Api.discardAgentCanvasVariationDraft("workflow-1", readyNode.node_id);

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(v2EtagStore.getWorkflow("workflow-1")).toBe('"workflow:workflow-1:revision:10"');
  });

  it("reads the frozen connection policy and proposal detail contracts", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/canvas/connection-policy")) {
        return jsonResponse({
          policy_version: "agent_canvas_connection_policy_v1",
          target_node_types: {
            text: ["text", "script"],
            script: ["text", "script"],
            image: ["text", "script", "image"],
            video: ["text", "script", "image", "video", "audio", "editing"],
            audio: ["text", "script"],
            editing: ["video", "audio", "editing"],
          },
          input_roles: [
            {
              source_node_type: "image",
              target_node_type: "video",
              roles: ["image_reference"],
              default_role: "image_reference",
            },
          ],
          image_asset_targets: {
            image: ["image_reference"],
            video: ["image_reference"],
          },
          binding_kind_by_source_type: {
            text: "text_context",
            script: "text_context",
            image: "image_reference",
            video: "video_reference",
            audio: "audio_reference",
            editing: "video_reference",
          },
          model_validation: {
            explicit_model: "authoring_and_run",
            automatic_model: "run",
          },
        });
      }
      return jsonResponse({
        proposal_id: "proposal-1",
        workflow_id: "workflow-1",
        turn_id: "turn-1",
        video_skill_run_id: "session-1",
        topic_id: "character",
        creative_direction_snapshot_id: null,
        proposal_revision: 1,
        source_proposal_id: null,
        proposal_kind: "character",
        specialist_name: "character_designer",
        options: [{
          option_id: "option-1",
          title: "Quiet confidence",
          summary_prompt: "A restrained editorial lead.",
        }],
        proposed_references: [],
        target_node_id: null,
        target_node_revision: null,
        proposal_purpose: null,
        availability: "open",
        application_count: 0,
        latest_application: null,
        guidance_session_id: "guidance-1",
        guidance_session_revision: 3,
        actions: [{
          action_id: "proposal-1:1:select_option",
          action: "select_option",
          label: "Select",
          proposal_id: "proposal-1",
          expected_session_revision: 3,
          confirmation_required: false,
          reason: "Create one editable Draft.",
        }],
        created_at: "2026-07-30T08:00:00Z",
        updated_at: "2026-07-30T08:00:00Z",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const policy = await v2Api.agentCanvasConnectionPolicy();
    const proposal = await v2Api.agentCanvasProposal("workflow-1", "proposal-1");

    expect(policy.input_roles[0]?.default_role).toBe("image_reference");
    expect(proposal.options[0]?.title).toBe("Quiet confidence");
  });

  it("creates connected nodes and patches bindings with real workflow preconditions", async () => {
    v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:7"');
    const binding = {
      binding_id: "binding-1",
      workflow_id: "workflow-1",
      source: { kind: "node_output", source_node_id: "node-image-1" },
      target_node_id: "node-video-1",
      input_role: "image_reference",
      required: true,
      enabled: true,
      order: 0,
      label: null,
      metadata: {},
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T08:00:00Z",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      expect(headers.get("If-Match")).toBe('"workflow:workflow-1:revision:7"');
      expect(headers.get("Idempotency-Key")).toBeTruthy();
      if (url.endsWith("/connected-nodes")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          anchor_node_id: "node-image-1",
          direction: "downstream",
          binding: {
            input_role: "image_reference",
            required: true,
          },
        });
        return jsonResponse({
          workflow_id: "workflow-1",
          revision: 8,
          layout_revision: 2,
          node: { ...draftNode, node_id: "node-video-1", node_type: "video", creative_role: "general_video" },
          binding,
          events_cursor: 20,
        }, { status: 201, etag: '"workflow:workflow-1:revision:8"' });
      }
      expect(JSON.parse(String(init?.body))).toEqual({
        input_role: "image_reference",
        required: false,
        enabled: false,
        order: 2,
      });
      return jsonResponse({
        workflow_id: "workflow-1",
        revision: 9,
        binding: { ...binding, required: false, enabled: false, order: 2 },
        incoming_bindings: [{ ...binding, required: false, enabled: false, order: 2 }],
        events_cursor: 21,
      }, { etag: '"workflow:workflow-1:revision:9"' });
    });
    vi.stubGlobal("fetch", fetchMock);

    const connected = await v2Api.createAgentCanvasConnectedNode(
      "workflow-1",
      {
        anchor_node_id: "node-image-1",
        direction: "downstream",
        node: {
          node_type: "video",
          creative_role: "general_video",
          title: "Video",
          generation_prompt: "Animate the product.",
          position: { x: 500, y: 80 },
        },
        binding: {
          input_role: "image_reference",
          required: true,
        },
      },
      "connected-key",
    );
    v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:7"');
    const patched = await v2Api.patchAgentCanvasBinding(
      "workflow-1",
      "binding-1",
      {
        input_role: "image_reference",
        required: false,
        enabled: false,
        order: 2,
      },
      "binding-patch-key",
    );

    expect(connected.value.node.node_id).toBe("node-video-1");
    expect(patched.value.binding.enabled).toBe(false);
  });

  it("applies guided actions by stable action id without sending button text", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toContain("/chat/guided-actions/action-1/apply");
      expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("guided-key");
      expect(JSON.parse(String(init?.body))).toEqual({ confirmed: true });
      return jsonResponse({
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        message_id: null,
        turn_id: "turn-guided-1",
        status: "queued",
        events_cursor: 22,
      }, { status: 202 });
    });
    vi.stubGlobal("fetch", fetchMock);
    v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:7"');

    const accepted = await v2Api.applyAgentCanvasGuidedAction(
      "workflow-1",
      "action-1",
      { confirmed: true },
      "guided-key",
    );

    expect(accepted.turn_id).toBe("turn-guided-1");
  });

  it("persists layout batches against layout_revision without semantic If-Match", async () => {
    v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:12"');
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("If-Match")).toBeNull();
      expect(JSON.parse(String(init?.body))).toEqual({
        expected_layout_revision: 4,
        positions: [
          { node_id: "node-image-1", x: 500, y: 260 },
          { node_id: "node-image-2", x: 860, y: 260 },
        ],
      });
      return jsonResponse({
        workflow_id: "workflow-1",
        revision: 12,
        layout_revision: 5,
        positions: [
          { node_id: "node-image-1", x: 500, y: 260 },
          { node_id: "node-image-2", x: 860, y: 260 },
        ],
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await v2Api.patchAgentCanvasLayout("workflow-1", {
      expected_layout_revision: 4,
      positions: [
        { node_id: "node-image-1", x: 500, y: 260 },
        { node_id: "node-image-2", x: 860, y: 260 },
      ],
    });

    expect(result.layout_revision).toBe(5);
    expect(v2EtagStore.getWorkflow("workflow-1")).toBe('"workflow:workflow-1:revision:12"');
  });

  it("cancels runs and Editing exports without synthetic idempotency headers", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("Idempotency-Key")).toBeNull();
      if (url.endsWith("/runs/execution-1/cancel")) {
        expect(JSON.parse(String(init?.body))).toEqual({ reason: "user_cancelled" });
        return jsonResponse({
          workflow_id: "workflow-1",
          execution_id: "execution-1",
          status: "cancelled",
          cancelled_node_ids: ["node-image-1"],
          events_cursor: 30,
        });
      }
      expect(url).toContain("/nodes/node-editing-1/exports/export-1/cancel");
      return jsonResponse({
        workflow_id: "workflow-1",
        node_id: "node-editing-1",
        export_id: "export-1",
        status: "cancelled",
        events_cursor: 31,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const run = await v2Api.cancelAgentCanvasRun(
      "workflow-1",
      "execution-1",
      { reason: "user_cancelled" },
    );
    const editing = await v2Api.cancelAgentCanvasEditingExport(
      "workflow-1",
      "node-editing-1",
      "export-1",
    );

    expect(run.status).toBe("cancelled");
    expect(editing.status).toBe("cancelled");
  });
});

describe("Agent Canvas Video Style catalog client", () => {
  it("lists catalog entries with backend filters and reads public Skill details", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://frontend.test");
      expect(init?.method).toBeUndefined();
      if (url.pathname.endsWith("/video-skills/platform-default")) {
        return jsonResponse({
          skill_id: "platform-default",
          version: "1.0.0",
          title: "Platform Default",
          summary: "Balanced commercial video direction.",
          category: "commercial-craft",
          tags: ["commercial"],
          supported_use_cases: ["general advertising"],
          preview: { kind: "none", summary: null, media_url: null },
          display_order: 10,
        });
      }
      expect(url.pathname).toBe("/api/v2/video-skills");
      expect(Object.fromEntries(url.searchParams)).toEqual({
        category: "commercial-craft",
        cursor: "Mg",
        limit: "40",
      });
      return jsonResponse({
        catalog_version: "1",
        categories: [{
          category_id: "commercial-craft",
          title: "Commercial Craft",
          display_order: 10,
        }],
        items: [],
        next_cursor: null,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const catalog = await v2Api.listVideoSkills({
      category: "commercial-craft",
      cursor: "Mg",
      limit: 40,
    });
    const detail = await v2Api.getVideoSkill("platform-default");

    expect(catalog.catalog_version).toBe("1");
    expect(catalog.categories[0]?.title).toBe("Commercial Craft");
    expect(detail.title).toBe("Platform Default");
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
