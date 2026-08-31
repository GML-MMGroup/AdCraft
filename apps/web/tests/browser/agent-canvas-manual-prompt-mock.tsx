import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../src/types-v2.ts";
import { AgentCanvasInlineWorkbench } from "../../src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";

const timestamp = "2026-08-31T10:00:00Z";

function manualNode(): CanvasNodeV2 {
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
    generation_prompt: null,
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
      status: "waiting_user",
      operation_id: null,
      presentation_stream_id: null,
      attempt_no: 0,
      context_snapshot_id: null,
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
      error: null,
      updated_at: timestamp,
    },
    variation_draft: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function App() {
  const [node, setNode] = useState(manualNode);
  const [events, setEvents] = useState<string[]>([]);
  const workflow = useMemo<AgentCanvasWorkflowV2>(() => ({
    workflow_id: node.workflow_id,
    project_id: "project-manual-prompt-mock",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [node],
    bindings: [],
    assets: [],
    active_style_skill: null,
  }), [node]);

  return (
    <main className="manual-prompt-mock">
      <AgentCanvasInlineWorkbench
        workflow={workflow}
        node={node}
        patchNode={async (_nodeId, patch) => {
          setEvents((current) => [...current, `patch-start:${String(patch.generation_prompt)}`]);
          await new Promise((resolve) => setTimeout(resolve, 250));
          setNode((current) => ({ ...current, generation_prompt: patch.generation_prompt ?? null }));
          setEvents((current) => [...current, "patch-complete"]);
        }}
        onRun={async (nextNode) => {
          setEvents((current) => [...current, `run:${nextNode.generation_prompt ?? ""}`]);
        }}
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
      <output data-testid="manual-prompt-events">{events.join("|")}</output>
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .manual-prompt-mock { width: min(100% - 32px, 560px); margin: 24px auto; font-family: Inter, sans-serif; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<App />);
