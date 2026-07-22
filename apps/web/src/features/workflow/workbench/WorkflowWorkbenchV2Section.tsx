import { V2SlotCard } from "../v2/slots/V2SlotCard.tsx";
import { v2EditableItemPrompt, v2ItemPromptLabel } from "../v2/v2PromptModel.ts";
import { runtimeForSlot, selectedAssetForSlot, workingVersionForSlot, historyVersionsForSlot } from "../../../workflow-v2/selectors.ts";
import type { WorkflowWorkbenchSurfaceActions, WorkflowWorkbenchSurfaceModel } from "./WorkflowWorkbenchSurface.tsx";

export function WorkflowWorkbenchV2Section({
  model,
  actions,
}: {
  model: WorkflowWorkbenchSurfaceModel;
  actions: WorkflowWorkbenchSurfaceActions;
}) {
  const {
    selectedPlanNode,
    selectedNodeUsesV2InlineRegionEditing,
    workflow,
    selectedV2Items,
    selectedV2SlotsByItemId,
    dynamicItemPromptDrafts,
    dynamicItemPromptSavingById,
    selectedAssets,
    selectedV2AssetVersions,
    workflowV2Runtime,
    workflowV2,
    v2SlotVersionsById,
    selectedV2ReferenceAssets,
    v2ProviderTaskRefreshKeyBySlotId,
    selectedFreeGenerationMediaType,
    selectedFreeAbsorbTargetNodes,
  } = model;
  const {
    refreshV2WorkflowGraph,
    syncV2Snapshot,
    changeDynamicItemPrompt,
    saveV2ItemPrompt,
    confirmV2ShotSummary,
    runSelectedV2Slot,
    loadV2SlotVersions,
    saveV2SlotPrompt,
    selectV2SlotVersion,
    discardV2WorkingVersion,
    deleteV2SelectedSlotAsset,
    pollV2ProviderTask,
    createV2FreeNode,
    generateV2FreeNode,
    absorbV2FreeNode,
    deleteV2FreeNode,
    removeV2Reference,
    currentWorkflowIsV2,
  } = actions;

  if (!selectedPlanNode) return null;
  if (currentWorkflowIsV2() && selectedPlanNode.id === "final-composition") return null;

  return (
    <>
      {selectedNodeUsesV2InlineRegionEditing ? (
        <section className="v2-inline-region-workbench-note" aria-label="V2 inline region editing">
          <div className="node-preview-heading">
            <span>Region card editing</span>
            <button
              className="small-action"
              type="button"
              onClick={() => {
                if (workflow?.workflow_id) void refreshV2WorkflowGraph(workflow.workflow_id);
              }}
            >
              Refresh V2
            </button>
          </div>
          <span className="empty-output">Click a product, character, or scene slot preview on the canvas to edit and regenerate that exact slot.</span>
        </section>
      ) : null}
      {currentWorkflowIsV2() && !selectedNodeUsesV2InlineRegionEditing ? (
        <section className="v2-node-workbench" aria-label="V2 item and slot workbench">
          <div className="node-preview-heading">
            <span>V2 items / slots</span>
            <button
              className="small-action"
              type="button"
              onClick={() => {
                if (workflow?.workflow_id) void refreshV2WorkflowGraph(workflow.workflow_id);
              }}
            >
              Refresh V2
            </button>
          </div>
          {selectedV2Items.map((item) => {
            const itemSlots = selectedV2SlotsByItemId.get(item.item_id) ?? [];
            const itemPromptDraft = dynamicItemPromptDrafts[item.item_id] ?? v2EditableItemPrompt(item);
            return (
              <article className="v2-workbench-item" key={item.item_id} data-v2-item-id={item.item_id}>
                <header className="v2-workbench-item-heading">
                  <strong>{item.display_name || item.item_id}</strong>
                  <span>{item.item_type}</span>
                  <em>{item.status}</em>
                </header>
                <label className="v2-item-prompt">
                  <span>{v2ItemPromptLabel(item)}</span>
                  <textarea value={itemPromptDraft} onChange={(event) => changeDynamicItemPrompt(item.item_id, event.target.value)} />
                </label>
                <div className="asset-revision-actions">
                  <button className="small-action" type="button" disabled={Boolean(dynamicItemPromptSavingById[item.item_id])} onClick={() => void saveV2ItemPrompt(item, itemPromptDraft)}>
                    Save item prompt
                  </button>
                  {item.shot_summary_prompt || item.shot_id ? (
                    <button className="small-action" type="button" onClick={() => void confirmV2ShotSummary(item)}>
                      Confirm shot summary
                    </button>
                  ) : null}
                </div>
                <div className="v2-workbench-slot-list">
                  {itemSlots.map((slot) => {
                    const slotRuntimeRecord = runtimeForSlot(workflowV2Runtime, slot.slot_id);
                    return (
                      <V2SlotCard
                        key={slot.slot_id}
                        slot={slot}
                        workflowId={workflow?.workflow_id}
                        selectedAsset={selectedAssetForSlot(slot, selectedV2AssetVersions)}
                        workingVersion={workingVersionForSlot(slot, selectedV2AssetVersions)}
                        historyVersions={historyVersionsForSlot(slot, selectedV2AssetVersions)}
                        slotVersions={v2SlotVersionsById[slot.slot_id] ?? null}
                        runtimeStatus={slotRuntimeRecord?.status}
                        runtimeRecord={slotRuntimeRecord}
                        referenceAssets={[...(workflowV2?.asset_versions ?? []), ...selectedV2ReferenceAssets]}
                        referenceRelations={workflowV2?.asset_relations ?? []}
                        onGenerate={(slotId) => runSelectedV2Slot(slotId)}
                        onLoadVersions={(slotId) => void loadV2SlotVersions(slotId)}
                        onSavePrompt={(slotId, prompt, negativePrompt) => saveV2SlotPrompt(slotId, prompt, negativePrompt)}
                        onSelectCurrentVersion={(slotId, versionId) => void selectV2SlotVersion(slotId, versionId)}
                        onDiscardWorkingVersion={(slotId) => void discardV2WorkingVersion(slotId)}
                        onDeleteSelectedAsset={(slotId) => void deleteV2SelectedSlotAsset(slotId)}
                        onPollProviderTask={(taskId) => void pollV2ProviderTask(taskId)}
                        providerTaskRefreshSignal={v2ProviderTaskRefreshKeyBySlotId[slot.slot_id] ?? 0}
                        onRefreshWorkflow={async () => {
                          if (!workflow?.workflow_id) return;
                          await refreshV2WorkflowGraph(workflow.workflow_id);
                          await syncV2Snapshot(workflow.workflow_id);
                        }}
                      />
                    );
                  })}
                </div>
              </article>
            );
          })}
          {!selectedV2Items.length ? <span className="empty-output">No V2 items for this node yet.</span> : null}
          {selectedPlanNode.node_type === "free-generation" || selectedPlanNode.id === "free-generation" ? (
            <div className="asset-revision-actions v2-free-node-actions">
              <button className="small-action" type="button" onClick={() => void createV2FreeNode()}>
                Create V2 free node
              </button>
              <button className="small-action" type="button" onClick={() => void generateV2FreeNode(selectedPlanNode.id)}>
                Generate V2 free node
              </button>
              {selectedAssets[0] ? (
                selectedFreeAbsorbTargetNodes.length ? (
                  selectedFreeAbsorbTargetNodes.map((targetNode) => (
                    <button className="small-action" type="button" key={targetNode.id} onClick={() => void absorbV2FreeNode(selectedPlanNode.id, selectedAssets[0].asset_id, targetNode.id)}>
                      Absorb selected asset into {targetNode.title || targetNode.id}
                    </button>
                  ))
                ) : (
                  <span className="empty-output">No compatible V2 absorb target for {selectedFreeGenerationMediaType ?? "this asset"}.</span>
                )
              ) : null}
              <button className="small-action" type="button" onClick={() => void deleteV2FreeNode(selectedPlanNode.id)}>
                Delete V2 free node
              </button>
            </div>
          ) : null}
          <button className="small-action" type="button" hidden onClick={() => void removeV2Reference("")}>
            Remove V2 reference relation
          </button>
        </section>
      ) : null}
    </>
  );
}
