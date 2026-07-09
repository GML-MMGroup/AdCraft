import { useMemo, useState } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import { buildAddSlotReferenceRequest, buildSlotLibraryReferenceRegistration } from "../../../../workflow-v2/slotControls.ts";
import { normalizeV2SlotAttachments } from "../operations/v2SlotOperationModel.ts";
import type { V2SlotAttachment, V2SlotOperationTarget } from "../operations/v2SlotOperationTypes.ts";
import { V2ReferenceAttachmentStrip } from "../references/V2ReferenceAttachmentStrip.tsx";

type V2LibraryReferenceOption = {
  entity_id: string;
  display_name?: string;
  library_asset_id?: string | null;
  semantic_type?: string | null;
};

type V2SlotReferenceComposerProps = {
  target: V2SlotOperationTarget;
  prompt: string;
  attachments: V2SlotAttachment[];
  libraryOptions?: V2LibraryReferenceOption[];
  semanticType?: string | null;
  onPromptChange: (prompt: string) => void;
  onRefreshReferences: () => Promise<void> | void;
};

export function V2SlotReferenceComposer({
  target,
  prompt,
  attachments,
  libraryOptions = [],
  semanticType,
  onPromptChange,
  onRefreshReferences,
}: V2SlotReferenceComposerProps) {
  const [busyAction, setBusyAction] = useState<"upload" | "library" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const normalizedAttachments = useMemo(() => normalizeV2SlotAttachments(attachments), [attachments]);

  async function uploadFiles(files: FileList | null) {
    if (!files?.length) return;
    const formData = new FormData();
    Array.from(files).forEach((file) => formData.append("files", file));
    formData.append("target_type", "slot");
    formData.append("slot_id", target.slotId);
    setBusyAction("upload");
    setError(null);
    try {
      const response = await v2Api.uploadSlotReferenceAsset(target.workflowId, target.slotId, formData);
      const uploadedAssets = response.assets.filter((asset) => asset.asset_id && asset.version_id);
      await Promise.all(
        uploadedAssets.map((asset) =>
          v2Api.attachSlotReference(target.workflowId, target.slotId, buildAddSlotReferenceRequest(asset, semanticType || asset.semantic_type || "reference")),
        ),
      );
      await onRefreshReferences();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload reference failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function attachLibraryReference(option: V2LibraryReferenceOption) {
    setBusyAction("library");
    setError(null);
    try {
      const registered = await v2Api.registerLibraryReference(
        target.workflowId,
        buildSlotLibraryReferenceRegistration(target.slotId, option.entity_id, option.library_asset_id, option.semantic_type ?? semanticType),
      );
      await v2Api.attachSlotReference(
        target.workflowId,
        target.slotId,
        buildAddSlotReferenceRequest(registered.asset, option.semantic_type || semanticType || registered.asset.semantic_type || "reference"),
      );
      await onRefreshReferences();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Attach library reference failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function removeAttachment(attachment: V2SlotAttachment) {
    setBusyAction("remove");
    setError(null);
    try {
      if (attachment.relationId) {
        await v2Api.removeReference(target.workflowId, attachment.relationId);
      }
      await onRefreshReferences();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Remove reference failed");
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
        <label className="small-action v2-slot-reference-upload">
          <span>{busyAction === "upload" ? "Uploading..." : "Upload reference"}</span>
          <input
            type="file"
            hidden
            multiple
            accept="image/*,video/*,audio/*"
            onChange={(event) => {
              void uploadFiles(event.currentTarget.files);
              event.currentTarget.value = "";
            }}
          />
        </label>
        {libraryOptions.length ? (
          <select
            value=""
            aria-label="Attach library reference"
            disabled={busyAction !== null}
            onChange={(event) => {
              const option = libraryOptions.find((item) => item.entity_id === event.currentTarget.value);
              if (option) void attachLibraryReference(option);
            }}
          >
            <option value="">Library reference</option>
            {libraryOptions.map((option) => (
              <option key={option.entity_id} value={option.entity_id}>
                {option.display_name || option.entity_id}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      {error ? <span className="v2-slot-reference-error">{error}</span> : null}
    </section>
  );
}
