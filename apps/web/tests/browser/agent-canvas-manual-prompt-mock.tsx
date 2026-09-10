import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import type { ProviderModelSummaryV1 } from "../../src/api/providerRegistry.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../src/types-v2.ts";
import { AgentCanvasInlineWorkbench } from "../../src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx";
import { AgentAssetBrowser } from "../../src/features/agent-canvas/assets/AgentAssetBrowser.tsx";
import { CloseIcon } from "../../src/icons.tsx";
import "../../src/features/agent-canvas/agent-canvas-page.css";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";

const timestamp = "2026-08-31T10:00:00Z";
const providerModel = {
  model_ref: "volcengine_ark:doubao-seedream-4-0",
  provider_id: "volcengine_ark",
  provider_model_id: "doubao-seedream-4-0",
  display_name: "Doubao Seedream 4.0",
  capability: "image",
  capability_metadata: {},
  availability: "available",
  unavailable_reason: null,
  catalog_revision: 4,
  adapter_id: "ark-image-v1",
  transport_kind: "ark_image_native",
  release_tier: "default",
  conformance_status: "certified",
  accepted_input_modes: ["text_only", "native_reference_slots"],
  parameter_schema_id: "ark-image-v1",
  parameter_descriptors: [
    {
      name: "resolution",
      value_type: "enum",
      allowed_values: ["1024x1024", "1536x1024"],
      minimum: null,
      maximum: null,
      default: null,
    },
  ],
  reference_policy: {
    modes: [{ mode: "native_reference_slots", max_references: 2, allowed_roles: ["product", "scene"] }],
    max_images: 2,
  },
} satisfies ProviderModelSummaryV1;

const videoModel: ProviderModelSummaryV1 = {
  ...providerModel,
  model_ref: "mock:video-toolbar",
  provider_model_id: "video-toolbar",
  display_name: "Video toolbar model",
  capability: "video",
  parameter_descriptors: [
    { name: "duration_seconds", value_type: "integer", allowed_values: [], minimum: 1, maximum: 15, default: null },
    { name: "resolution", value_type: "enum", allowed_values: ["720p", "1080p"], minimum: null, maximum: null, default: null },
    { name: "aspect_ratio", value_type: "enum", allowed_values: ["16:9", "9:16"], minimum: null, maximum: null, default: null },
    { name: "audio_mode", value_type: "enum", allowed_values: ["native", "silent"], minimum: null, maximum: null, default: null },
  ],
};

function manualNode(
  preparationStatus: "waiting_user" | "queued" | "failed" | "superseded" = "waiting_user",
): CanvasNodeV2 {
  return {
    node_id: "manual-image-node",
    workflow_id: "workflow-manual-prompt-mock",
    node_type: "image",
    creative_role: "general_image",
    role_contract_version: "ad-media-role-v2",
    title: "Image",
    status: "draft",
    execution_mode: "generative",
    summary_prompt: null,
    generation_prompt: preparationStatus === "waiting_user" ? null : "Existing generation prompt",
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    prompt_preparation: {
      status: preparationStatus,
      operation_id: preparationStatus === "waiting_user" ? null : "prompt-operation-1",
      presentation_stream_id: null,
      attempt_no: preparationStatus === "waiting_user" ? 0 : 1,
      context_snapshot_id: preparationStatus === "waiting_user" ? null : "prompt-context-1",
      occurrence_id: null,
      character_phase: null,
      prompt_digest: null,
      role_variant: null,
      recipe_id: null,
      recipe_version: null,
      recipe_digest: null,
      requirement_revision_id: null,
      requirement_revision_no: null,
      document_revisions: {},
      binding_digest: null,
      style_projection_digest: null,
      brief_digest: null,
      parameter_origins: [],
      compaction_policy_version: null,
      compaction_policy_digest: null,
      compaction_decisions: [],
      assertion_evidence: null,
      attempt_stage: null,
      error: preparationStatus === "failed"
        ? { code: "prompt_preparation_failed", message: "Preparation failed.", retryable: true }
        : null,
      updated_at: timestamp,
    },
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function App() {
  const searchParams = new URLSearchParams(window.location.search);
  const preparation = searchParams.get("preparation");
  const referenceCount = Math.min(20, Math.max(0, Number(searchParams.get("references")) || 0));
  const [removedReferences, setRemovedReferences] = useState<string[]>([]);
  const referenceNodes = useMemo(() => Array.from({ length: referenceCount }, (_, index) => ({
    ...manualNode(), node_id: `reference-${index}`, title: `Reference ${index + 1}`,
    status: "ready" as const, output_asset_id: "reference-asset",
  })), [referenceCount]);
  const useProviderContract = searchParams.get("provider") === "1";
  const textPanel = searchParams.get("textPanel");
  const assetBrowserMode = searchParams.get("assetBrowser");
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [assetAction, setAssetAction] = useState("");
  const testModelMenu = searchParams.get("modelMenu") === "1";
  const audioToggle = searchParams.get("audioToggle");
  const testManualVideo = searchParams.get("manualVideo") === "1";
  const testVideoToolbar = searchParams.get("videoToolbar") === "1" || audioToggle !== null || testManualVideo;
  const audioModel: ProviderModelSummaryV1 = {
    ...videoModel,
    parameter_descriptors: [
      ...videoModel.parameter_descriptors!.filter((descriptor) => descriptor.name !== "audio_mode"),
      { name: "generate_audio", value_type: "boolean", allowed_values: [], minimum: null, maximum: null, default: audioToggle === "on" },
    ],
  };
  const silentModel: ProviderModelSummaryV1 = { ...videoModel, model_ref: "mock:no-audio", display_name: "Silent model" };
  const textModel: ProviderModelSummaryV1 = {
    ...providerModel, model_ref: "mock:text", provider_model_id: "text", capability: "text",
    display_name: "Text generation model", parameter_descriptors: [], reference_policy: null,
  };
  const providerModels = textPanel ? [textModel, {
    ...textModel, model_ref: "mock:text-unverified", display_name: "Unverified text model", conformance_status: "unverified" as const,
  }] : testVideoToolbar ? testManualVideo ? [audioModel] : audioToggle !== null ? [audioModel, silentModel] : [videoModel] : testModelMenu ? [
    { ...providerModel, display_name: "Studio Image Model With A Long Descriptive Display Name" },
    {
      ...providerModel,
      model_ref: "mock:unverified-image",
      display_name: "Unverified image model",
      conformance_status: "unverified" as const,
    },
  ] : [providerModel];
  const initialPreparation = preparation === "queued"
    || preparation === "failed"
    || preparation === "superseded"
    ? preparation
    : "waiting_user";
  const [node, setNode] = useState<CanvasNodeV2>(() => textPanel ? {
    ...manualNode(initialPreparation), node_type: "text", node_id: "text-panel-node",
    creative_role: textPanel === "world" ? "world_setting" : "general_text",
    status: textPanel === "world" || textPanel === "ready" ? "ready" : textPanel === "failed" ? "failed" : "draft",
    generation_prompt: textPanel === "draft" ? null : "Existing text prompt",
    structured_content: textPanel === "world" || textPanel === "ready" ? { content: "Existing text content", retained_field: "keep" } : {},
  } : testVideoToolbar ? {
    ...manualNode(initialPreparation),
    node_type: "video",
    creative_role: "general_video",
    generation_prompt: testManualVideo ? null : "Animate a studio product shot.",
    parameters: testManualVideo ? {} : audioToggle !== null ? { duration_seconds: 8, resolution: "1080p", aspect_ratio: "16:9" } : { audio_mode: "native" },
  } : manualNode(initialPreparation));
  const [lastParameters, setLastParameters] = useState<Record<string, unknown> | null>(null);
  const [events, setEvents] = useState<string[]>([]);
  const workflow = useMemo<AgentCanvasWorkflowV2>(() => ({
    workflow_id: node.workflow_id,
    project_id: "project-manual-prompt-mock",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [...referenceNodes, node],
    bindings: referenceNodes.filter((reference) => !removedReferences.includes(reference.node_id)).map((reference, order) => ({
      binding_id: reference.node_id, workflow_id: node.workflow_id,
      source: { kind: "node_output" as const, source_node_id: reference.node_id },
      target_node_id: node.node_id, input_role: "visual_reference", enabled: true, order,
      label: null, metadata: {}, created_at: timestamp, updated_at: timestamp,
    })),
    assets: referenceCount ? [{
      asset_id: "reference-asset", project_id: "project-manual-prompt-mock", workflow_id: node.workflow_id,
      media_type: "image", source_type: "upload", display_name: "Reference image", status: "ready",
      mime_type: "image/webp", size_bytes: 0, storage_key: null,
      preview_url: "/brand/adcraft-icon.webp", media_url: "/brand/adcraft-icon.webp",
      width: 1254, height: 1254, duration_seconds: null, checksum: "reference-preview",
      source_semantic_role: null, source_node_id: null, source_execution_id: null,
      provider: null, model_id: null, prompt_provenance: {}, quality_metadata: {}, created_at: timestamp,
    }] : [],
    active_style_skill: null,
  }), [node, referenceNodes, referenceCount, removedReferences]);

  return (
    <main className={`manual-prompt-mock${assetBrowserMode ? " has-asset-browser" : ""}`}>
      <AgentCanvasInlineWorkbench
        workflow={workflow}
        node={node}
        deleteBinding={async (bindingId) => setRemovedReferences((current) => [...current, bindingId])}
        patchNode={async (_nodeId, patch) => {
          setEvents((current) => [...current, `patch-start:${String(patch.generation_prompt)}`]);
          await new Promise((resolve) => setTimeout(resolve, 250));
          if (testVideoToolbar && patch.parameters) setLastParameters(patch.parameters);
          setNode((current) => ({
            ...current,
            ...(patch.generation_prompt !== undefined ? { generation_prompt: patch.generation_prompt } : {}),
            ...(patch.structured_content ? { structured_content: patch.structured_content } : {}),
            ...(patch.model_selection_mode ? { model_selection_mode: patch.model_selection_mode } : {}),
            ...(patch.model_ref !== undefined ? { model_ref: patch.model_ref } : {}),
          }));
          setEvents((current) => [...current, "patch-complete"]);
        }}
        onRun={async (nextNode) => {
          setEvents((current) => [...current, `run:${nextNode.generation_prompt ?? ""}`]);
        }}
        onDiscardVariation={async () => undefined}
        onMaterializeVariation={async () => null}
        onSaveImageToLibrary={async () => undefined}
        onDelete={async () => undefined}
        onOpenEditing={() => undefined}
        onOpenAssets={() => { if (assetBrowserMode) setAssetsOpen(true); }}
        onUploadReferences={() => undefined}
        onClose={() => undefined}
        providerModels={useProviderContract || testVideoToolbar || textPanel ? providerModels : undefined}
        providerDefaultModelRef={useProviderContract || testVideoToolbar || textPanel ? providerModels[0].model_ref : undefined}
      />
      {assetsOpen ? (
        <div className="agent-canvas-overlay agent-canvas-overlay--assets" role="dialog" aria-modal="true" aria-label="Project assets">
          <button type="button" className="agent-canvas-overlay__close" aria-label="Close assets" onClick={() => setAssetsOpen(false)}><CloseIcon /></button>
          <AgentAssetBrowser
            workflowId={node.workflow_id}
            onAddReferences={async (selections) => {
              await new Promise((resolve) => setTimeout(resolve, 150));
              if (assetBrowserMode === "error") throw new Error("Unable to attach this reference. Try another image.");
              setAssetAction(JSON.stringify(selections));
            }}
            onCreateReadySourceNode={(selection) => setAssetAction(JSON.stringify(selection))}
          />
        </div>
      ) : null}
      {assetBrowserMode ? <output data-testid="asset-browser-action">{assetAction}</output> : null}
      <output data-testid="manual-prompt-events">{events.join("|")}</output>
      <output data-testid="manual-node-status">{node.status}</output>
      {textPanel ? <output data-testid="text-panel-content">{JSON.stringify(node.structured_content)}</output> : null}
      {testVideoToolbar ? <output data-testid="video-toolbar-parameters">{JSON.stringify(lastParameters)}</output> : null}
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .manual-prompt-mock { width: min(100% - 32px, 560px); margin: 24px auto; font-family: Inter, sans-serif; }
  .manual-prompt-mock.has-asset-browser { position: relative; min-height: 620px; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<App />);
