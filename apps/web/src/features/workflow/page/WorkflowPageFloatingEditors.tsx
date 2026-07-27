import { useCallback, useEffect, useState } from "react";
import { LocalPromptComposer, type PromptGenerateContext } from "../../../components/PromptComposer.tsx";
import { WorkflowDraggablePanel, type PanelOffset } from "../../../components/WorkflowDraggablePanel.tsx";
import { AssetsIcon, CloseIcon, SaveIcon } from "../../../icons";
import { effectiveSlotPrompt, type WorkflowSlotV2 } from "../../../types-v2.ts";
import { assetLibraryEntityTypeForV2ImageSlot } from "../v2/slots/v2SlotAssetLibraryModel.ts";
import type { SlotMicroEditDraft } from "../v2/slots/useSlotMicroEdit.ts";
import { v2EditableItemPrompt } from "../v2/v2PromptModel.ts";
import { V2BgmReferenceAttachments } from "./V2BgmReferenceAttachments.tsx";
import type { WorkflowPageFloatingEditorsArgs } from "./workflowPageContracts.ts";
import { workflowPageFloatingEditorVisibility } from "./workflowPageSurfaceBuilders.ts";
import { v2SlotComposerPresentation } from "./v2SlotComposerPresentation.ts";

export function WorkflowPageFloatingEditors(args: WorkflowPageFloatingEditorsArgs) {
  const activeSlotId = args.activeV2SlotId;
  const activeStoryboardItemId = args.activeV2StoryboardItemId;
  const activeStoryboardItem = activeStoryboardItemId
    ? args.workflowItems.find((item) => item.item_id === activeStoryboardItemId)
    : undefined;
  const storyboardPromptDraft =
    activeStoryboardItemId && activeStoryboardItem
      ? args.storyboardPromptDrafts[activeStoryboardItemId] ??
        v2EditableItemPrompt(activeStoryboardItem)
      : "";
  const storyboardPromptSaving = Boolean(
    activeStoryboardItemId &&
      args.storyboardPromptSavingById[activeStoryboardItemId],
  );
  const activeSlotDraft =
    activeSlotId && args.activeV2Slot
      ? args.slotDraftsById[activeSlotId] ?? draftFromV2Slot(args.activeV2Slot)
      : undefined;
  const activeSlotPresentation = args.activeV2Slot
    ? v2SlotComposerPresentation(args.activeV2Slot)
    : null;
  const isBgmSlot = activeSlotPresentation?.assetPickerEnabled === false;
  const { showSlotComposer, showStoryboardComposer } =
    workflowPageFloatingEditorVisibility({
      isV2: args.isV2,
      hasActiveSlotId: Boolean(activeSlotId),
      slotIsEditable: Boolean(activeSlotPresentation?.editable),
      hasSlotDraft: Boolean(activeSlotDraft),
      hasActiveStoryboardItemId: Boolean(activeStoryboardItemId),
      hasStoryboardItem: Boolean(activeStoryboardItem),
    });
  const activeSlotSupportsLibraryResource = Boolean(
    assetLibraryEntityTypeForV2ImageSlot(args.activeV2Slot),
  );

  const [slotComposerOffset, setSlotComposerOffset] = useState<PanelOffset>({ x: 0, y: 0 });
  const [slotComposerAnchor, setSlotComposerAnchor] = useState<{
    slotId: string;
    left: number;
    top: number;
  } | null>(null);
  const activeSlotComposerAnchor =
    slotComposerAnchor?.slotId === activeSlotId ? slotComposerAnchor : null;
  const [storyboardPromptOffset, setStoryboardPromptOffset] = useState<PanelOffset>({
    x: 0,
    y: 0,
  });
  const [storyboardPromptAnchor, setStoryboardPromptAnchor] = useState<{
    itemId: string;
    left: number;
    top: number;
  } | null>(null);
  const activeStoryboardPromptAnchor =
    storyboardPromptAnchor?.itemId === activeStoryboardItemId
      ? storyboardPromptAnchor
      : null;

  useEffect(() => {
    setSlotComposerOffset({ x: 0, y: 0 });
    if (!activeSlotId) {
      setSlotComposerAnchor(null);
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const page = document.querySelector<HTMLElement>(".workflow-page");
      const slotTarget = Array.from(
        document.querySelectorAll<HTMLElement>("[data-slot-action-target]"),
      ).find(
        (element) => element.dataset.slotActionTarget === activeSlotId,
      );
      const pageRect = page?.getBoundingClientRect();
      const slotRect = slotTarget?.getBoundingClientRect();
      if (!pageRect || !slotRect) {
        setSlotComposerAnchor(null);
        return;
      }
      const panelWidth = Math.min(410, Math.max(320, pageRect.width - 48));
      const left = Math.min(
        Math.max(slotRect.left - pageRect.left, 24),
        Math.max(24, pageRect.width - panelWidth - 24),
      );
      const top = Math.min(
        Math.max(slotRect.bottom - pageRect.top + 10, 24),
        Math.max(24, pageRect.height - 300),
      );
      setSlotComposerAnchor({ slotId: activeSlotId, left, top });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeSlotId]);

  const commitSlotComposerOffset = useCallback(
    (_panelKey: string, offset: PanelOffset) => setSlotComposerOffset(offset),
    [],
  );

  useEffect(() => {
    setStoryboardPromptOffset({ x: 0, y: 0 });
    if (!activeStoryboardItemId) {
      setStoryboardPromptAnchor(null);
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const page = document.querySelector<HTMLElement>(".workflow-page");
      const summaryTarget = Array.from(
        document.querySelectorAll<HTMLElement>("[data-storyboard-summary-action-target]"),
      ).find(
        (element) =>
          element.dataset.storyboardSummaryActionTarget === activeStoryboardItemId,
      );
      const pageRect = page?.getBoundingClientRect();
      const summaryRect = summaryTarget?.getBoundingClientRect();
      if (!pageRect || !summaryRect) {
        setStoryboardPromptAnchor(null);
        return;
      }
      const panelWidth = Math.min(430, Math.max(320, pageRect.width - 48));
      const left = Math.min(
        Math.max(summaryRect.left - pageRect.left, 24),
        Math.max(24, pageRect.width - panelWidth - 24),
      );
      const top = Math.min(
        Math.max(summaryRect.bottom - pageRect.top + 10, 24),
        Math.max(24, pageRect.height - 280),
      );
      setStoryboardPromptAnchor({
        itemId: activeStoryboardItemId,
        left,
        top,
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeStoryboardItemId]);

  const commitStoryboardPromptOffset = useCallback(
    (_panelKey: string, offset: PanelOffset) => setStoryboardPromptOffset(offset),
    [],
  );

  return (
    <>
      {showSlotComposer &&
      activeSlotComposerAnchor &&
      args.activeV2Slot &&
      activeSlotId &&
      activeSlotDraft ? (
        <WorkflowDraggablePanel
          panelKey="v2-slot-composer"
          offset={slotComposerOffset}
          className="v2-floating-slot-composer nodrag"
          headingClassName="v2-floating-slot-composer-heading"
          style={{
            left: activeSlotComposerAnchor.left,
            top: activeSlotComposerAnchor.top,
            bottom: "auto",
          }}
          heading={
            <>
              <span>{activeSlotPresentation?.heading}</span>
              <button
                type="button"
                className="v2-floating-slot-composer-close"
                aria-label={activeSlotPresentation?.closeLabel}
                title={activeSlotPresentation?.closeLabel}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  args.setActiveV2SlotId(null);
                }}
              >
                <CloseIcon />
              </button>
            </>
          }
          onOffsetCommit={commitSlotComposerOffset}
        >
          <div
            className="v2-floating-slot-composer-body"
            data-floating-slot-composer-id={activeSlotId}
            data-v2-local-prompt-composer-target={`slot:${activeSlotId}`}
          >
            {isBgmSlot ? (
              <V2BgmReferenceAttachments
                attachments={activeSlotDraft.attachments}
                disabled={activeSlotDraft.isSubmitting}
                onRemove={(attachment) => {
                  args.removeV2SlotReference(activeSlotId, {
                    source:
                      attachment.source === "asset_library"
                        ? "library_entity"
                        : attachment.source === "upload"
                          ? "uploaded_asset"
                          : "reference_asset",
                    asset_id:
                      attachment.source_asset_id ??
                      (attachment.source === "upload" ? attachment.id : undefined),
                    entity_id: attachment.library_entity_id ?? undefined,
                    relation_id: attachment.relation_id,
                    library_asset_id: attachment.library_asset_id,
                  });
                }}
              />
            ) : null}
            <LocalPromptComposer
              draftIdentity={activeSlotId}
              placeholder={activeSlotPresentation?.placeholder ?? "Ask the agent team..."}
              initialValue={activeSlotDraft.prompt}
              disabled={activeSlotDraft.isSubmitting}
              acceptedFileTypes={activeSlotPresentation?.acceptedFileTypes}
              assetPickerEnabled={activeSlotPresentation?.assetPickerEnabled}
              assetMentionsEnabled={activeSlotPresentation?.assetMentionsEnabled}
              assetMentionContext={{
                workflowId: args.workflowId ?? undefined,
                nodeId: args.activeV2Slot.node_id,
              }}
              referenceScope="item_revision"
              referenceTargetContext={{
                referenceScope: "item_revision",
                nodeId: args.activeV2Slot.node_id,
                itemId: args.activeV2Slot.item_id,
                semanticType: args.activeV2Slot.slot_type,
              }}
              onUploadInputAsset={isBgmSlot ? undefined : args.uploadV2PromptInputAsset}
              onUploadFile={
                isBgmSlot
                  ? (file) => args.uploadV2SlotReference(activeSlotId, [file])
                  : undefined
              }
              onDraftChange={(prompt, context) => {
                args.changeV2SlotPrompt(activeSlotId, prompt);
                args.syncV2SlotPromptReferences(activeSlotId, context);
              }}
              onGenerate={(prompt: string, context?: PromptGenerateContext) =>
                void args.submitV2LocalSlotPrompt(activeSlotId, prompt, context)
              }
              secondaryActions={
                !isBgmSlot && activeSlotSupportsLibraryResource ? (
                  <>
                    <button
                      className="pill-btn icon-only"
                      type="button"
                      aria-label="Replace from asset library"
                      title="Replace from asset library"
                      disabled={activeSlotDraft.isSubmitting}
                      onClick={() =>
                        args.openV2SlotAssetLibraryReplace(activeSlotId)
                      }
                    >
                      <AssetsIcon />
                    </button>
                    <button
                      className="pill-btn icon-only"
                      type="button"
                      aria-label="Save as resource"
                      title="Save as resource"
                      disabled={activeSlotDraft.isSubmitting}
                      onClick={() =>
                        args.openV2SlotAssetLibrarySave(activeSlotId)
                      }
                    >
                      <SaveIcon />
                    </button>
                  </>
                ) : null
              }
            />
          </div>
        </WorkflowDraggablePanel>
      ) : null}

      {showStoryboardComposer &&
      activeStoryboardPromptAnchor &&
      activeStoryboardItem &&
      activeStoryboardItemId ? (
        <WorkflowDraggablePanel
          panelKey="v2-storyboard-prompt-composer"
          offset={storyboardPromptOffset}
          className="v2-floating-slot-composer v2-floating-storyboard-composer nodrag"
          headingClassName="v2-floating-slot-composer-heading"
          style={{
            left: activeStoryboardPromptAnchor.left,
            top: activeStoryboardPromptAnchor.top,
            bottom: "auto",
          }}
          heading={
            <>
              <span>
                {activeStoryboardItem.display_name || activeStoryboardItem.item_id}
              </span>
              <button
                type="button"
                className="v2-floating-slot-composer-close"
                aria-label="Close storyboard prompt"
                title="Close storyboard prompt"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  args.setActiveV2StoryboardItemId(null);
                }}
              >
                <CloseIcon />
              </button>
            </>
          }
          onOffsetCommit={commitStoryboardPromptOffset}
        >
          <div
            className="v2-floating-slot-composer-body"
            data-v2-local-prompt-composer-target={`storyboard:${activeStoryboardItemId}`}
          >
            <LocalPromptComposer
              placeholder="Ask the agent team..."
              initialValue={storyboardPromptDraft}
              disabled={storyboardPromptSaving}
              assetMentionContext={{
                workflowId: args.workflowId ?? undefined,
                nodeId: activeStoryboardItem.node_id,
              }}
              referenceScope="item_revision"
              referenceTargetContext={{
                referenceScope: "item_revision",
                nodeId: activeStoryboardItem.node_id,
                itemId: activeStoryboardItem.item_id,
              }}
              onUploadInputAsset={args.uploadV2PromptInputAsset}
              onGenerate={(prompt: string, context?: PromptGenerateContext) =>
                void args.submitV2StoryboardPrompt(activeStoryboardItem, prompt, context)
              }
            />
          </div>
        </WorkflowDraggablePanel>
      ) : null}
    </>
  );
}

function draftFromV2Slot(slot: WorkflowSlotV2): SlotMicroEditDraft {
  return {
    prompt: effectiveSlotPrompt(slot),
    negative_prompt: slot.negative_prompt ?? "",
    reference_asset_ids: [...(slot.explicit_reference_ids ?? [])],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: (slot.explicit_reference_ids ?? []).map((assetId) => ({
      id: `reference:${assetId}`,
      source: "reference_asset",
      source_asset_id: assetId,
      status: "attached",
    })),
    dirty: false,
    promptDirty: false,
    referenceDirty: false,
    base_prompt: effectiveSlotPrompt(slot),
    base_negative_prompt: slot.negative_prompt ?? "",
    isSubmitting: false,
  };
}
