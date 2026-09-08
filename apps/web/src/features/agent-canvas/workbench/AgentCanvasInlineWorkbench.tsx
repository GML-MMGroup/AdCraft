import { useEffect } from "react";

import { EditingWorkbench } from "./EditingWorkbench.tsx";
import { MediaPromptWorkbench } from "./MediaPromptWorkbench.tsx";
import { NodeReferenceStrip } from "./NodeReferenceStrip.tsx";
import { NodePromptPreparationState } from "./NodePromptPreparationState.tsx";
import { NodeWorkbenchShell } from "./NodeWorkbenchShell.tsx";
import { ScriptWorkbench } from "./ScriptWorkbench.tsx";
import { TextWorkbench } from "./TextWorkbench.tsx";
import { useNodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import type { AgentCanvasInlineWorkbenchProps } from "./workbenchTypes.ts";
import { isNodePromptReady } from "../model/promptPreparation.ts";
import "./agent-canvas-inline-workbench.css";

export function AgentCanvasInlineWorkbench(props: AgentCanvasInlineWorkbenchProps) {
  return <VisibleAgentCanvasInlineWorkbench {...props} />;
}

function VisibleAgentCanvasInlineWorkbench(props: AgentCanvasInlineWorkbenchProps) {
  const {
    workflow,
    node,
    visibleStatus,
    deleteBinding,
    providerModels = [],
    providerModelsLoading = false,
    providerModelsError = null,
    modelResolution = null,
    onClose,
    onRetryPromptPreparation,
    onWorkflowRefresh,
    onOpenAssets,
    onUploadReferences,
    onOpenEditing,
  } = props;
  const draft = useNodeWorkbenchDraft(props);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  if (node.execution_mode === "source_only") {
    return null;
  }

  const references = node.node_type === "editing" ? null : (
    <NodeReferenceStrip
      workflow={workflow}
      node={node}
      deleteBinding={deleteBinding}
      pending={draft.pending}
      perform={draft.perform}
    />
  );
  const requiresPreparedPrompt = ["text", "script", "image", "video", "audio"].includes(node.node_type)
    && !(node.node_type === "text" && node.creative_role === "world_setting");
  const promptReady = !requiresPreparedPrompt || isNodePromptReady(node);
  const promptPreparing = requiresPreparedPrompt && !promptReady;

  return (
    <NodeWorkbenchShell
      nodeType={node.node_type}
    >
      {references}
      {promptPreparing ? (
        <NodePromptPreparationState
          node={node}
          onRetryPromptPreparation={onRetryPromptPreparation}
          onWorkflowRefresh={onWorkflowRefresh}
        />
      ) : null}
      {node.node_type === "text" ? (
        <TextWorkbench
          node={node}
          draft={draft}
          models={providerModels}
          modelsLoading={providerModelsLoading}
          modelsError={providerModelsError}
          modelResolution={modelResolution}
          promptReady={promptReady}
        />
      ) : null}
      {node.node_type === "script" ? (
        <ScriptWorkbench
          node={node}
          status={visibleStatus ?? node.status}
          draft={draft}
          models={providerModels}
          modelsLoading={providerModelsLoading}
          modelsError={providerModelsError}
          modelResolution={modelResolution}
          promptReady={promptReady}
        />
      ) : null}
      {["image", "video", "audio"].includes(node.node_type) && promptReady ? (
        <MediaPromptWorkbench
          node={node}
          draft={draft}
          models={providerModels}
          modelsLoading={providerModelsLoading}
          modelsError={providerModelsError}
          modelResolution={modelResolution}
          onOpenAssets={onOpenAssets}
          onUploadReferences={onUploadReferences}
        />
      ) : null}
      {node.node_type === "editing" ? (
        <EditingWorkbench workflow={workflow} node={node} onOpenEditing={onOpenEditing} />
      ) : null}
    </NodeWorkbenchShell>
  );
}
