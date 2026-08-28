import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { v2EtagStore } from "../../src/api/v2EtagStore.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../src/types-v2.ts";
import { AgentCanvasNodeCard } from "../../src/features/agent-canvas/canvas/AgentCanvasNode.tsx";
import { AgentCanvasEditingPanel } from "../../src/features/agent-canvas/editing/AgentCanvasEditingPanel.tsx";
import { AgentCanvasInlineWorkbench } from "../../src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx";
import {
  mergeAgentCanvasEditingExportImport,
  mergeAgentCanvasWorkflow,
} from "../../src/features/agent-canvas/session/workflowMerge.ts";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";

const timestamp = "2026-08-27T00:00:00Z";

function node(
  nodeId: string,
  nodeType: CanvasNodeV2["node_type"],
  outputAssetId: string | null,
  position: CanvasNodeV2["position"],
): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "video" ? "general_video" : nodeType === "audio" ? "bgm" : "editing",
    role_contract_version: "ad-media-role-v2",
    title: nodeType === "editing" ? "Final composition" : nodeType === "video" ? "Source video" : "BGM",
    status: outputAssetId ? "ready" : "draft",
    execution_mode: "generative",
    summary_prompt: null,
    generation_prompt: nodeType === "editing" ? null : "Mock generation prompt",
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: outputAssetId,
    position,
    revision: 1,
    error: null,
    prompt_preparation: null,
    variation_draft: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function asset(
  assetId: string,
  mediaType: ProjectAssetSummaryV2["media_type"],
  displayName: string,
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    version_id: `version-${assetId}`,
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: mediaType,
    source_type: mediaType === "video" && assetId === "asset-export" ? "editing_export" : "generated",
    semantic_type: null,
    display_name: displayName,
    mime_type: mediaType === "video" ? "video/mp4" : "audio/mpeg",
    status: "ready",
    size_bytes: 1024,
    storage_key: null,
    preview_url: mediaType === "video" ? "/assets/home-product-film.mp4" : null,
    media_url: "/assets/home-product-film.mp4",
    width: mediaType === "video" ? 1920 : null,
    height: mediaType === "video" ? 1080 : null,
    duration_seconds: 30,
    checksum: `sha256-${assetId}`,
    source_semantic_role: null,
    source_node_id: null,
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: {},
    quality_metadata: {},
    created_at: timestamp,
  };
}

function binding(
  bindingId: string,
  sourceNodeId: string,
  targetNodeId: string,
  inputRole: CanvasBindingV2["input_role"],
  order: number,
): CanvasBindingV2 {
  return {
    binding_id: bindingId,
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: sourceNodeId },
    target_node_id: targetNodeId,
    input_role: inputRole,
    required: true,
    enabled: true,
    order,
    label: null,
    metadata: {},
    created_at: timestamp,
    updated_at: timestamp,
  };
}

const sourceVideo = node("video-source", "video", "asset-video-source", { x: 40, y: 80 });
const bgm = node("audio-source", "audio", "asset-audio-source", { x: 40, y: 400 });
const downstream = node("editing-downstream", "editing", null, { x: 1100, y: 160 });
const editing = {
  ...node("editing-1", "editing", null, { x: 620, y: 160 }),
  structured_content: {
    manifest: {
      video_entries: [{
        binding_id: "binding-video-editing",
        asset_id: null,
        enabled: true,
        timeline_start_seconds: 0,
        trim_start_seconds: 0,
        trim_end_seconds: 30,
        volume: 1,
        preserve_native_audio: true,
        transition: "cut",
        transition_duration_seconds: 0,
        fit_mode: "fit",
      }],
      bgm: {
        binding_id: "binding-audio-editing",
        asset_id: null,
        enabled: true,
        trim_start_seconds: 0,
        trim_end_seconds: 30,
        volume: 0.35,
        fade_in_seconds: 0,
        fade_out_seconds: 0,
      },
      output: {
        resolution: "1920x1080",
        aspect_ratio: "16:9",
        fps: 30,
        video_codec: "h264",
        audio_codec: "aac",
        container: "mp4",
      },
      manifest_revision: 5,
      timeline_duration_seconds: 30,
    },
    dirty: false,
    preview: {
      clips: [{
        reference_id: "binding-video-editing",
        binding_id: "binding-video-editing",
        node_id: "video-source",
        asset_id: "asset-video-source",
        status: "ready",
        display_order: 0,
        preview_url: "/assets/home-product-film.mp4",
        duration_seconds: 30,
        warning: null,
      }],
      bgm_binding_id: "binding-audio-editing",
      bgm_node_id: "audio-source",
      bgm_asset_id: "asset-audio-source",
      estimated_duration_seconds: 30,
      warnings: [],
    },
    last_successful_export: null,
    active_export: null,
  },
};

const completedExport = {
  export_id: "export-30s",
  status: "completed" as const,
  manifest_revision: 5,
  fingerprint: "fingerprint-export-30s",
  ready_video_node_ids: ["video-source"],
  skipped_inputs: [],
  bgm_node_id: "audio-source",
  output_asset_id: "asset-export",
  error: null,
  started_at: timestamp,
  finished_at: timestamp,
};

const initialWorkflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 8,
  layout_revision: 3,
  nodes: [sourceVideo, bgm, editing, downstream],
  bindings: [
    binding("binding-video-editing", "video-source", "editing-1", "video_reference", 0),
    binding("binding-audio-editing", "audio-source", "editing-1", "audio_reference", 1),
  ],
  assets: [
    asset("asset-video-source", "video", "Input video"),
    asset("asset-audio-source", "audio", "Input BGM"),
  ],
  active_style_skill: null,
};

v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:8"');

function AcceptanceHarness() {
  const [workflow, setWorkflow] = useState(initialWorkflow);
  const [editingPanelOpen, setEditingPanelOpen] = useState(true);
  const [previewAssetId, setPreviewAssetId] = useState<string | null>(null);
  const [issue, setIssue] = useState<string | null>(null);
  const importedNode = workflow.nodes.find((candidate) => candidate.node_id === "video-export") ?? null;
  const importedAsset = importedNode?.output_asset_id
    ? workflow.assets.find((candidate) => candidate.asset_id === importedNode.output_asset_id) ?? null
    : null;
  const downstreamBinding = workflow.bindings.find((candidate) => (
    candidate.source.kind === "node_output"
    && candidate.source.source_node_id === "video-export"
    && candidate.target_node_id === "editing-downstream"
  ));
  const authoritativeImportBinding = workflow.bindings.find((candidate) => (
    candidate.binding_id === "binding-editing-export"
  ));
  const editingNode = useMemo(
    () => workflow.nodes.find((candidate) => candidate.node_id === "editing-1")!,
    [workflow.nodes],
  );

  useEffect(() => {
    const completeExport = () => {
      v2EtagStore.set("workflow", "workflow-1", '"workflow:workflow-1:revision:9"');
      setWorkflow((current) => ({
        ...current,
        revision: 9,
        nodes: current.nodes.map((candidate) => candidate.node_id === "editing-1"
          ? {
              ...candidate,
              status: "ready",
              output_asset_id: "asset-export",
              revision: candidate.revision + 1,
              structured_content: {
                ...candidate.structured_content,
                dirty: false,
                last_successful_export: completedExport,
                active_export: null,
              },
            }
          : candidate),
        assets: current.assets.some((candidate) => candidate.asset_id === "asset-export")
          ? current.assets
          : [...current.assets, asset("asset-export", "video", "AdCraft Final 30s")],
      }));
    };
    window.addEventListener("mock-editing-export-completed", completeExport);
    return () => window.removeEventListener("mock-editing-export-completed", completeExport);
  }, []);

  const addToCanvas = async (exportId: string) => {
    setIssue(null);
    try {
      const response = await agentCanvasApi.importAgentCanvasEditingExport(
        workflow.workflow_id,
        editingNode.node_id,
        { export_id: exportId, title: "Exported video", position: { x: 900, y: 160 } },
        "mock-editing-export-import",
      );
      setWorkflow((current) => mergeAgentCanvasEditingExportImport(current, response.value));
      setEditingPanelOpen(false);
    } catch (error) {
      setIssue(error instanceof Error ? error.message : "Import failed");
    }
  };

  const connectDownstream = async () => {
    if (!importedNode) return;
    setIssue(null);
    try {
      const response = await agentCanvasApi.createAgentCanvasBinding(workflow.workflow_id, {
        source: { kind: "node_output", source_node_id: importedNode.node_id },
        target_node_id: "editing-downstream",
        input_role: "video_reference",
        required: true,
        enabled: true,
        order: 0,
      });
      setWorkflow((current) => mergeAgentCanvasWorkflow(current, response.value.workflow));
    } catch (error) {
      setIssue(error instanceof Error ? error.message : "Binding failed");
    }
  };

  return (
    <main style={{ minHeight: "100vh", padding: 18, background: "#0a0a0a", color: "#f5f5f5" }}>
      {editingPanelOpen ? (
        <AgentCanvasEditingPanel
          workflow={workflow}
          node={editingNode}
          patchNode={async () => undefined}
          onClose={() => setEditingPanelOpen(false)}
          onAddExportToCanvas={addToCanvas}
        />
      ) : null}
      {issue ? <p role="alert">{issue}</p> : null}
      {importedNode && importedAsset ? (
        <section aria-label="Authoritative imported canvas result" style={{ marginTop: 24 }}>
          <div className="agent-canvas-node-shell">
            <AgentCanvasNodeCard
              node={importedNode}
              asset={importedAsset}
              onOpenVideoPreview={(_nodeId, selectedAsset) => setPreviewAssetId(selectedAsset.asset_id)}
            />
          </div>
          <div data-testid="imported-workbench">
            <AgentCanvasInlineWorkbench
              workflow={workflow}
              node={importedNode}
              patchNode={async () => undefined}
              onRun={async () => undefined}
              onSaveVariation={async () => undefined}
              onDiscardVariation={async () => undefined}
              onMaterializeVariation={async () => null}
              onSaveImageToLibrary={async () => undefined}
              onDelete={async () => undefined}
              onOpenEditing={() => undefined}
              onOpenAssets={() => undefined}
              onUploadReferences={() => undefined}
              onClose={() => undefined}
            />
          </div>
          <p data-testid="import-binding">
            {authoritativeImportBinding
              ? `${authoritativeImportBinding.source.kind}:${authoritativeImportBinding.target_node_id}`
              : "No import binding"}
          </p>
          <button type="button" onClick={() => void connectDownstream()}>
            Connect imported video downstream
          </button>
          <p data-testid="downstream-binding">
            {downstreamBinding ? downstreamBinding.binding_id : "Not connected"}
          </p>
        </section>
      ) : null}
      {previewAssetId && importedAsset ? (
        <video
          aria-label="Imported source-only video preview"
          src={importedAsset.media_url ?? undefined}
          controls
        />
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);
