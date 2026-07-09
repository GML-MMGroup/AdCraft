import { AssetMentionInput } from "../../../components/PromptComposer";
import { RunCurrentIcon, UploadIcon } from "../../../icons";
import type { AssetLibraryUploadKind } from "../../../types.ts";
import { NodeAttachmentPreview } from "../components/NodeAttachmentPreview.tsx";
import { LibraryReferenceChips } from "../assets/LibraryReferenceChips.tsx";
import type { WorkflowWorkbenchSurfaceActions, WorkflowWorkbenchSurfaceModel } from "./WorkflowWorkbenchSurface.tsx";

export function WorkflowWorkbenchPromptSection({
  model,
  actions,
}: {
  model: WorkflowWorkbenchSurfaceModel;
  actions: WorkflowWorkbenchSurfaceActions;
}) {
  const {
    selectedPlanNode,
    workflow,
    selectedEditablePrompt,
    nodePromptMentionReferences,
    selectedSystemSuggestion,
    hasNewSystemSuggestion,
    selectedOptimizedPrompt,
    selectedProviderPrompt,
    workflowRunning,
    uploadingAsset,
    nodeAssetInputRef,
    nodeUploadKind,
    nodeUploadName,
    nodeUploadTags,
    assetLibraryUploadKindOptions,
    nodeRunLibraryEntities,
    nodeRunPrimaryReferenceIds,
    currentNodeRunning,
  } = model;
  const {
    updateSelectedPrompt,
    setNodePromptMentionReferences,
    applySystemSuggestion,
    regenerateOptimizedPrompt,
    applyOptimizedPrompt,
    uploadAssetForSelectedNode,
    setNodeUploadKind,
    setNodeUploadName,
    setNodeUploadTags,
    setPickerTarget,
    removeSelectedInputAsset,
    openMediaLightbox,
    removeLibraryEntityForTarget,
    togglePrimaryReferenceForTarget,
    currentWorkflowIsV2,
    runNode,
    runSelectedV2Slot,
  } = actions;

  if (!selectedPlanNode) return null;

  return (
    <div className="prompt-composer is-compact node-workbench-composer">
      <label className="node-prompt-field">
        <span>Editable prompt</span>
        <AssetMentionInput
          value={selectedEditablePrompt}
          placeholder="Describe the local adjustment for this node."
          mentionReferences={nodePromptMentionReferences}
          workflowId={workflow?.workflow_id}
          nodeId={selectedPlanNode.id}
          onChange={(nextValue, nextReferences) => {
            updateSelectedPrompt(nextValue);
            setNodePromptMentionReferences(nextReferences);
          }}
        />
      </label>

      {selectedSystemSuggestion ? (
        <div className={`prompt-insight-panel ${hasNewSystemSuggestion ? "has-new-system-suggestion" : ""}`}>
          <div className="prompt-insight-heading">
            <span>System suggestion</span>
            {hasNewSystemSuggestion ? <em>New</em> : null}
            <button className="small-action" type="button" onClick={applySystemSuggestion}>
              Apply suggestion
            </button>
          </div>
          <p>{selectedSystemSuggestion}</p>
        </div>
      ) : null}

      <div className="prompt-insight-panel">
        <div className="prompt-insight-heading">
          <span>Optimized generation prompt</span>
          <button className="small-action" type="button" disabled={workflowRunning || uploadingAsset} onClick={() => void regenerateOptimizedPrompt()}>
            Regenerate optimized
          </button>
          <button className="small-action" type="button" disabled={!selectedOptimizedPrompt} onClick={applyOptimizedPrompt}>
            Apply optimized
          </button>
        </div>
        {selectedOptimizedPrompt ? <p>{selectedOptimizedPrompt}</p> : <p className="empty-output">No optimized prompt yet.</p>}
        {selectedProviderPrompt ? (
          <details className="provider-prompt-details">
            <summary>Provider prompt</summary>
            <pre>{selectedProviderPrompt}</pre>
          </details>
        ) : null}
      </div>

      <div className="composer-footer node-workbench-footer">
        <div className="composer-tools node-workbench-tools">
          <input
            ref={nodeAssetInputRef}
            type="file"
            hidden
            multiple
            accept="image/*,video/*,audio/*,.pdf,.txt,.md,.doc,.docx,application/pdf,text/plain,text/markdown,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(event) => {
              void uploadAssetForSelectedNode(event.target.files);
              event.currentTarget.value = "";
            }}
          />
          <div className="node-upload-options" aria-label="Upload asset library metadata">
            <select value={nodeUploadKind} onChange={(event) => setNodeUploadKind(event.target.value as AssetLibraryUploadKind)}>
              {assetLibraryUploadKindOptions.map((option) => (
                <option key={option.value || "auto"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input value={nodeUploadName} placeholder="Name" onChange={(event) => setNodeUploadName(event.target.value)} />
            <input value={nodeUploadTags} placeholder="Tags" onChange={(event) => setNodeUploadTags(event.target.value)} />
          </div>
          <button className="pill-btn icon-only" aria-label="Upload file" title="Upload file" onClick={() => nodeAssetInputRef.current?.click()} disabled={uploadingAsset}>
            <UploadIcon />
          </button>
          <button className="pill-btn library-reference-trigger" type="button" onClick={() => setPickerTarget("node")}>
            Library reference
          </button>
          <div className="asset-preview-section">
            <span className="asset-preview-heading">Input assets</span>
            <div className="node-attachment-list asset-preview-list" aria-label="Input assets">
              {(selectedPlanNode.input_assets ?? []).map((asset) => (
                <NodeAttachmentPreview key={asset.asset_id} asset={asset} onRemove={() => removeSelectedInputAsset(asset.asset_id)} onOpen={() => openMediaLightbox(asset)} />
              ))}
              {!selectedPlanNode.input_assets?.length ? <em>No assets attached.</em> : null}
            </div>
            <LibraryReferenceChips
              entities={nodeRunLibraryEntities}
              primaryReferenceIds={new Set(nodeRunPrimaryReferenceIds)}
              onRemove={(entityId) => removeLibraryEntityForTarget("node", entityId)}
              onTogglePrimary={(entity) => togglePrimaryReferenceForTarget("node", entity)}
            />
          </div>
        </div>
        <button className="send-btn node-run-submit icon-only" aria-label="Run current only" title="Run current only" disabled={workflowRunning || currentNodeRunning || uploadingAsset} onClick={() => currentWorkflowIsV2() ? void runSelectedV2Slot() : void runNode()}>
          <RunCurrentIcon />
        </button>
      </div>
    </div>
  );
}

