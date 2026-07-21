import { useMemo, useState } from "react";
import { isV2ApiError, v2Api } from "../../../../api/v2Client.ts";
import type { V2ReferenceSelectionsRequest } from "../../../../types-v2.ts";
import { normalizeV2SlotAttachments } from "../operations/v2SlotOperationModel.ts";
import type { V2SlotAttachment, V2SlotOperationTarget } from "../operations/v2SlotOperationTypes.ts";
import { V2ReferenceAttachmentStrip } from "../references/V2ReferenceAttachmentStrip.tsx";
import { V2AssetReferencePicker } from "./V2AssetReferencePicker.tsx";

type V2SlotReferenceComposerProps = {
  target: V2SlotOperationTarget;
  prompt: string;
  attachments: V2SlotAttachment[];
  onPromptChange: (prompt: string) => void;
  onRefreshReferences: () => Promise<void> | void;
};

function fallbackWorkflowEtag(workflowId: string, stateVersion?: number) {
  return typeof stateVersion === "number" ? `"wf-${workflowId}-v${stateVersion}"` : null;
}

export function V2SlotReferenceComposer({ target, prompt, attachments, onPromptChange, onRefreshReferences }: V2SlotReferenceComposerProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<"attach" | "remove" | null>(null);
  const [workflowEtag, setWorkflowEtag] = useState<string | null>(null);
  const [bindingOrder, setBindingOrder] = useState<Array<{ bindingId: string; assetId: string; versionId: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const normalizedAttachments = useMemo(() => {
    const normalized = normalizeV2SlotAttachments(attachments);
    if (!bindingOrder.length) return normalized;
    const orderByBinding = new Map(bindingOrder.map((binding, index) => [binding.bindingId, index]));
    const orderByAssetVersion = new Map(bindingOrder.map((binding, index) => [`${binding.assetId}:${binding.versionId}`, index]));
    return [...normalized].sort((left, right) => {
      const leftOrder = orderByBinding.get(left.relationId ?? "") ?? orderByAssetVersion.get(`${left.sourceAssetId}:${left.sourceVersionId ?? ""}`) ?? Number.MAX_SAFE_INTEGER;
      const rightOrder = orderByBinding.get(right.relationId ?? "") ?? orderByAssetVersion.get(`${right.sourceAssetId}:${right.sourceVersionId ?? ""}`) ?? Number.MAX_SAFE_INTEGER;
      return leftOrder - rightOrder;
    });
  }, [attachments, bindingOrder]);

  async function currentEtag() {
    if (workflowEtag) return workflowEtag;
    const response = await v2Api.workflowWithEtag(target.workflowId);
    const nextEtag = response.etag ?? fallbackWorkflowEtag(target.workflowId, response.value.state_version);
    if (!nextEtag) throw new Error("The workflow revision is unavailable. Refresh the workflow and try again.");
    setWorkflowEtag(nextEtag);
    return nextEtag;
  }

  async function resyncAfterConflict() {
    const response = await v2Api.workflowWithEtag(target.workflowId);
    setWorkflowEtag(response.etag ?? fallbackWorkflowEtag(target.workflowId, response.value.state_version));
    await onRefreshReferences();
  }

  async function addReferences(request: V2ReferenceSelectionsRequest): Promise<boolean> {
    setBusyAction("attach");
    setError(null);
    try {
      const response = await v2Api.attachReferenceSelections(target.workflowId, target.slotId, request, await currentEtag());
      setWorkflowEtag(response.etag ?? fallbackWorkflowEtag(target.workflowId, response.value.workflow?.state_version) ?? workflowEtag);
      setBindingOrder(response.value.bindings.map((binding) => ({ bindingId: binding.binding_id, assetId: binding.asset_id, versionId: binding.version_id })));
      await onRefreshReferences();
      return true;
    } catch (caught) {
      if (isV2ApiError(caught) && caught.status === 412) {
        await resyncAfterConflict();
        setError("References changed in another edit. The workflow was refreshed; your selection is still available.");
        return false;
      }
      const message = caught instanceof Error ? caught.message : "Could not attach references";
      setError(message);
      throw caught;
    } finally {
      setBusyAction(null);
    }
  }

  async function removeAttachment(attachment: V2SlotAttachment) {
    if (!attachment.relationId) {
      setError("This reference does not include a binding id yet. Refresh the workflow before removing it.");
      return;
    }
    setBusyAction("remove");
    setError(null);
    try {
      const response = await v2Api.removeReferenceBinding(target.workflowId, attachment.relationId, await currentEtag());
      setWorkflowEtag(response.etag ?? fallbackWorkflowEtag(target.workflowId, response.value.workflow?.state_version) ?? workflowEtag);
      const removedBindingId = response.value.removed_binding_id ?? attachment.relationId;
      setBindingOrder((current) => current.filter((binding) => binding.bindingId !== removedBindingId));
      await onRefreshReferences();
    } catch (caught) {
      if (isV2ApiError(caught) && caught.status === 412) {
        await resyncAfterConflict();
        setError("References changed in another edit. The workflow was refreshed; nothing was removed locally.");
      } else {
        setError(caught instanceof Error ? caught.message : "Could not remove reference");
      }
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className="v2-slot-reference-composer nodrag" data-slot-reference-composer={target.slotId} onPointerDown={(event) => event.stopPropagation()}>
      <label className="v2-slot-prompt">
        <span>Slot prompt</span>
        <textarea value={prompt} style={{ resize: "vertical" }} onChange={(event) => onPromptChange(event.currentTarget.value)} />
      </label>
      <V2ReferenceAttachmentStrip attachments={normalizedAttachments} onRemove={(attachment) => void removeAttachment(attachment)} />
      <div className="v2-slot-reference-actions">
        <button className="small-action" type="button" disabled={busyAction !== null} onClick={() => setPickerOpen(true)}>
          Add reference
        </button>
        {busyAction === "remove" ? <span>Removing reference...</span> : null}
      </div>
      {error ? <span className="v2-slot-reference-error">{error}</span> : null}
      {pickerOpen ? <V2AssetReferencePicker workflowId={target.workflowId} slotId={target.slotId} onAddReferences={addReferences} onClose={() => setPickerOpen(false)} /> : null}
    </section>
  );
}
