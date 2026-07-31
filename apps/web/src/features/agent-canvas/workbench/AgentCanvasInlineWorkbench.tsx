import { useEffect } from "react";

import { EditingWorkbench } from "./EditingWorkbench.tsx";
import { MediaPromptWorkbench } from "./MediaPromptWorkbench.tsx";
import { NodeReferenceStrip } from "./NodeReferenceStrip.tsx";
import { NodeWorkbenchShell } from "./NodeWorkbenchShell.tsx";
import { ScriptWorkbench } from "./ScriptWorkbench.tsx";
import { TextWorkbench } from "./TextWorkbench.tsx";
import { useNodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import type { AgentCanvasInlineWorkbenchProps } from "./workbenchTypes.ts";
import "./agent-canvas-inline-workbench.css";

export function AgentCanvasInlineWorkbench(props: AgentCanvasInlineWorkbenchProps) {
  const {
    workflow,
    node,
    patchBinding,
    deleteBinding,
    connectionPolicy,
    providerCapabilities = [],
    providerCapabilitiesLoading = false,
    providerCapabilitiesError = null,
    onDelete,
    onClose,
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

  const deleteCurrentNode = async () => {
    const deleted = await draft.perform(() => onDelete(node.node_id));
    if (deleted) onClose();
  };

  const references = node.node_type === "editing" ? null : (
    <NodeReferenceStrip
      workflow={workflow}
      node={node}
      connectionPolicy={connectionPolicy}
      patchBinding={patchBinding}
      deleteBinding={deleteBinding}
      pending={draft.pending}
      perform={draft.perform}
    />
  );

  return (
    <NodeWorkbenchShell
      nodeType={node.node_type}
      title={node.title}
      status={node.status}
      pending={draft.pending}
      onDelete={() => void deleteCurrentNode()}
      onClose={onClose}
    >
      {references}
      {node.node_type === "text" ? <TextWorkbench node={node} draft={draft} /> : null}
      {node.node_type === "script" ? <ScriptWorkbench node={node} draft={draft} /> : null}
      {["image", "video", "audio"].includes(node.node_type) ? (
        <MediaPromptWorkbench
          node={node}
          draft={draft}
          capabilities={providerCapabilities}
          capabilitiesLoading={providerCapabilitiesLoading}
          capabilitiesError={providerCapabilitiesError}
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
