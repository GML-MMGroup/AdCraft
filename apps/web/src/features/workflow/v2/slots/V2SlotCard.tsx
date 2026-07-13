import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { effectiveSlotPrompt, type AssetVersionV2, type RuntimeRecordV2, type SlotVersionsResponseV2, type V2ReferenceAttachRequest, type WorkflowSlotV2 } from "../../../../types-v2.ts";
import { dedupeSlotVersionAssets, isIdOnlyAssetVersion, outdatedHintForSlot, providerAuditForSlot, safeProviderSnapshotText, usableAssetVersionUrl } from "../../../../workflow-v2/selectors.ts";
import { buildV2SlotTarget, normalizeV2SlotVersionState } from "../operations/v2SlotOperationModel.ts";
import type { V2SlotAttachment } from "../operations/v2SlotOperationTypes.ts";
import { V2ReferencePicker } from "../references/V2ReferencePicker.tsx";
import { V2ReferenceAuditPanel } from "../references/V2ReferenceAuditPanel.tsx";
import { V2ProviderTaskPanel } from "../provider/V2ProviderTaskPanel.tsx";
import { useV2MediaContextMenu } from "../media/useV2MediaContextMenu.ts";
import { V2SlotReferenceComposer } from "./V2SlotReferenceComposer.tsx";
import { V2SlotVersionActions } from "./V2SlotVersionActions.tsx";
import { createSlotPromptEditorState, rebaseSlotPromptEditorState } from "./slotPromptEditorState.ts";

type V2SlotCardProps = {
  slot: WorkflowSlotV2;
  workflowId?: string | null;
  selectedAsset?: AssetVersionV2;
  workingVersion?: AssetVersionV2;
  historyVersions?: AssetVersionV2[];
  runtimeStatus?: string;
  runtimeRecord?: RuntimeRecordV2;
  onGenerate?: (slotId: string) => Promise<unknown> | unknown;
  onLoadVersions?: (slotId: string) => void;
  onSavePrompt?: (slotId: string, prompt: string, negativePrompt?: string) => Promise<unknown> | unknown;
  onSelectCurrentVersion?: (slotId: string, versionId: string) => void;
  onDiscardWorkingVersion?: (slotId: string) => void;
  onDeleteSelectedAsset?: (slotId: string) => void;
  onPollProviderTask?: (taskId: string) => void;
  providerTaskRefreshSignal?: number;
  onRefreshWorkflow?: () => Promise<void> | void;
  slotVersions?: SlotVersionsResponseV2 | null;
  referenceAssets?: Array<{ asset_id: string; version_id?: string | null; display_name?: string; media_type?: string; public_url?: string | null; preview_url?: string | null }>;
  libraryOptions?: Array<{ entity_id: string; display_name?: string; library_asset_id?: string | null; semantic_type?: string | null }>;
  onAttachReference?: (request: V2ReferenceAttachRequest) => void;
};

const SLOT_LABELS: Record<string, string> = {
  product_main_image: "Product image",
  product_multi_view_grid: "Product multi-view",
  character_main_image: "Character image",
  character_three_view: "Character three-view",
  scene_main_image: "Scene image",
  scene_multi_view_grid: "Scene multi-view",
  bgm_audio: "BGM",
  shot_cell_1: "Shot cell 1",
  shot_cell_2: "Shot cell 2",
  shot_cell_3: "Shot cell 3",
  shot_cell_4: "Shot cell 4",
  shot_video_segment: "Shot video",
  final_video: "Final video",
  free_output: "Free output",
};

function assetLabel(asset?: AssetVersionV2) {
  if (!asset) return "None";
  if (isIdOnlyAssetVersion(asset)) return "Asset metadata syncing";
  return asset.public_url || asset.file_path || asset.asset_id;
}

function V2AssetVersionPreview({ asset, label }: { asset?: AssetVersionV2; label: string }) {
  const copyReference = useV2MediaContextMenu();
  const onContextMenu = (event: ReactMouseEvent) => {
    if (!asset?.asset_id || !asset.version_id) return;
    event.preventDefault();
    void copyReference(asset.asset_id, asset.version_id);
  };
  if (!asset) return <span>None</span>;
  const url = usableAssetVersionUrl(asset);
  if (!url) {
    return (
      <span className="v2-asset-syncing" data-asset-id={asset.asset_id}>
        Asset metadata syncing
      </span>
    );
  }
  if (asset.media_type === "image") {
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Right-click copies the V2 asset locator; normal image click behavior is unchanged.
    return <img src={url} alt={label} loading="lazy" decoding="async" onContextMenu={onContextMenu} />;
  }
  if (asset.media_type === "video") return <video src={url} controls preload="metadata" onContextMenu={onContextMenu} />;
  if (asset.media_type === "audio") return <audio src={url} controls preload="metadata" onContextMenu={onContextMenu} />;
  return <span>{url}</span>;
}

export function V2SlotCard({
  slot,
  workflowId,
  selectedAsset,
  workingVersion,
  historyVersions = [],
  runtimeStatus,
  runtimeRecord,
  onGenerate,
  onLoadVersions,
  onSavePrompt,
  onSelectCurrentVersion,
  onDiscardWorkingVersion,
  onDeleteSelectedAsset,
  onPollProviderTask,
  providerTaskRefreshSignal,
  onRefreshWorkflow,
  slotVersions,
  referenceAssets = [],
  libraryOptions = [],
  onAttachReference,
}: V2SlotCardProps) {
  const effectivePrompt = effectiveSlotPrompt(slot);
  const { slot_prompt, system_suggested_prompt, user_prompt, negative_prompt } = slot;
  const serverPromptState = useMemo(
    () => createSlotPromptEditorState({ slot_prompt, system_suggested_prompt, user_prompt, negative_prompt }),
    [negative_prompt, slot_prompt, system_suggested_prompt, user_prompt],
  );
  const [promptState, setPromptState] = useState(serverPromptState);
  useEffect(() => {
    setPromptState((current) => rebaseSlotPromptEditorState(current, serverPromptState));
  }, [serverPromptState]);
  const workingIsSelected = Boolean(workingVersion && selectedAsset && workingVersion.asset_id === selectedAsset.asset_id);
  const versionHistory = dedupeSlotVersionAssets(slotVersions?.versions?.length ? slotVersions.versions : historyVersions);
  const referenceAttachments = slotReferencesAsAttachments(slot, referenceAssets);
  const versionState = normalizeV2SlotVersionState({
    selected_version_id: selectedAsset?.version_id,
    selected_asset_id: selectedAsset?.asset_id ?? slot.selected_asset_id,
    working_version_id: workingVersion?.version_id ?? slot.current_working_version_id ?? slotVersions?.current_working_version_id,
    working_asset_id: workingVersion?.asset_id ?? slot.current_working_asset_id ?? slotVersions?.working_asset_id,
    history_versions: versionHistory,
    quality_status: workingVersion?.quality_status ?? selectedAsset?.quality_status,
  });
  const outdatedHint = outdatedHintForSlot(slot);
  const advancedPromptFields = [
    ["Dialogue prompt", slot.dialogue_prompt],
    ["Audio description prompt", slot.audio_description_prompt],
    ["Voice style prompt", slot.voice_style_prompt],
    ["Negative constraints", slot.negative_constraints],
  ].filter((entry): entry is [string, string] => typeof entry[1] === "string" && Boolean(entry[1].trim()));
  const providerAudit = providerAuditForSlot(slot, runtimeRecord, workingVersion ?? selectedAsset);
  const providerPromptSnapshot = safeProviderSnapshotText(providerAudit.provider_prompt_snapshot);
  const providerPayloadSnapshot = safeProviderSnapshotText(providerAudit.provider_payload_snapshot);
  const agentRouteSnapshot = safeProviderSnapshotText(providerAudit.agent_route_snapshot);
  const materializerWarnings = providerAudit.materializer_warnings.map(formatProviderWarning);
  const providerStatusItems = [
    ["materializer_mode", providerAudit.materializer_mode],
    ["model_id", providerAudit.model_id],
    ["provider", providerAudit.provider],
    ["provider_model", providerAudit.provider_model],
    ["task_status", providerAudit.task_status],
    ["provider_task_id", providerAudit.provider_task_id],
    ["remote_task_id", providerAudit.remote_task_id],
    ["last_error_code", providerAudit.last_error_code],
    ["last_error_message", providerAudit.last_error_message],
  ].filter((entry): entry is [string, string] => typeof entry[1] === "string" && Boolean(entry[1].trim()));
  const providerWaiting = providerAudit.task_status ? ["submitted", "running", "waiting"].includes(providerAudit.task_status) : false;
  const materializerFallback = providerAudit.materializer_mode ? ["fallback", "mock"].includes(providerAudit.materializer_mode) : false;
  const slotWaiting = providerWaiting || runtimeStatus === "waiting" || slot.status === "waiting";
  const referenceAudit = referenceAuditForSlot(slot, runtimeRecord, workingVersion ?? selectedAsset);
  const slotLabel = SLOT_LABELS[slot.slot_type] ?? slot.slot_type.replace(/_/g, " ");
  const { prompt: slotPrompt, negativePrompt, dirty: promptDirty } = promptState;

  function changeSlotPrompt(prompt: string) {
    setPromptState((current) => ({ ...current, prompt, dirty: prompt !== current.basePrompt || current.negativePrompt !== current.baseNegativePrompt }));
  }

  function changeNegativePrompt(nextNegativePrompt: string) {
    setPromptState((current) => ({ ...current, negativePrompt: nextNegativePrompt, dirty: current.prompt !== current.basePrompt || nextNegativePrompt !== current.baseNegativePrompt }));
  }

  async function savePrompt() {
    await onSavePrompt?.(slot.slot_id, slotPrompt, negativePrompt);
    setPromptState((current) => ({ ...current, basePrompt: current.prompt, baseNegativePrompt: current.negativePrompt, dirty: false }));
  }

  async function generateSlotVersion() {
    if (promptDirty) {
      await savePrompt();
    }
    await onGenerate?.(slot.slot_id);
  }

  return (
    <article className="v2-slot-card" data-slot-id={slot.slot_id} data-slot-type={slot.slot_type}>
      <header className="v2-slot-card-header">
        <span>{slotLabel}</span>
        <span className="v2-slot-status">{runtimeStatus || slot.status}</span>
      </header>
      {outdatedHint.active ? (
        <aside className="v2-slot-outdated-hint" aria-label="Reference updated">
          <strong>{outdatedHint.label || "Reference updated"}</strong>
          <span>Based on an older reference</span>
          {outdatedHint.sources.length ? <small>{outdatedHint.sources.map((source) => source.source_slot_id || source.source_asset_id || source.reason).filter(Boolean).join(" · ")}</small> : null}
        </aside>
      ) : null}
      {providerStatusItems.length || materializerWarnings.length ? (
        <section className="v2-provider-status" aria-label="Provider task status">
          {providerWaiting ? <strong>Generating / waiting for provider</strong> : null}
          {materializerFallback ? <em>Materializer is using {providerAudit.materializer_mode} mode</em> : null}
          <div className="v2-provider-status-grid">
            {providerStatusItems.map(([label, value]) => (
              <span key={label}>
                <b>{label}</b>
                <i>{value}</i>
              </span>
            ))}
          </div>
          {materializerWarnings.length ? (
            <ul>
              {materializerWarnings.map((warning, index) => (
                <li key={`${warning}-${index}`}>{warning}</li>
              ))}
            </ul>
          ) : null}
          {providerWaiting && providerAudit.provider_task_id && onPollProviderTask ? (
            <button type="button" onClick={() => onPollProviderTask(providerAudit.provider_task_id!)}>
              Poll provider task
            </button>
          ) : null}
        </section>
      ) : null}
      <section className="v2-slot-version v2-slot-selected">
        <strong>Selected version</strong>
        <V2AssetVersionPreview asset={selectedAsset} label={`${slot.slot_type} selected`} />
        <span>{assetLabel(selectedAsset)}</span>
        {selectedAsset && isIdOnlyAssetVersion(selectedAsset) ? (
          <button type="button" onClick={() => onLoadVersions?.(slot.slot_id)}>
            Refresh metadata
          </button>
        ) : null}
        {selectedAsset ? (
          <button type="button" onClick={() => onDeleteSelectedAsset?.(slot.slot_id)}>
            Delete selected asset
          </button>
        ) : null}
      </section>
      <section className="v2-slot-version v2-slot-working">
        <strong>Working version</strong>
        <V2AssetVersionPreview asset={workingVersion} label={`${slot.slot_type} working`} />
        <span>{assetLabel(workingVersion)}</span>
        {workingVersion && isIdOnlyAssetVersion(workingVersion) ? (
          <button type="button" onClick={() => onLoadVersions?.(slot.slot_id)}>
            Refresh metadata
          </button>
        ) : null}
        {workingVersion && !workingIsSelected ? <em>Not used in current workflow</em> : null}
      </section>
      {workflowId ? (
        <V2SlotVersionActions
          target={buildV2SlotTarget({
            workflowId,
            nodeId: slot.node_id,
            itemId: slot.item_id,
            slotId: slot.slot_id,
            assetId: workingVersion?.asset_id ?? selectedAsset?.asset_id ?? null,
            versionId: workingVersion?.version_id ?? selectedAsset?.version_id ?? null,
          })}
          versionState={versionState}
          onGenerateVersion={generateSlotVersion}
          onRefreshSlot={async () => {
            onLoadVersions?.(slot.slot_id);
          }}
          onRefreshWorkflow={async () => {
            await onRefreshWorkflow?.();
          }}
        />
      ) : (
        <div className="v2-slot-version-actions">
          <button type="button" disabled={slot.status === "blocked" || slot.status === "waiting" || slot.status === "skipped"} onClick={() => onGenerate?.(slot.slot_id)}>
            Generate a version
          </button>
          {workingVersion && !workingIsSelected ? (
            <button type="button" onClick={() => onSelectCurrentVersion?.(slot.slot_id, workingVersion.version_id)}>
              Use this version
            </button>
          ) : null}
          {workingVersion && !workingIsSelected ? (
            <button type="button" onClick={() => onDiscardWorkingVersion?.(slot.slot_id)}>
              Discard working version
            </button>
          ) : null}
        </div>
      )}
      {workflowId ? (
        <V2SlotReferenceComposer
          target={buildV2SlotTarget({
            workflowId,
            nodeId: slot.node_id,
            itemId: slot.item_id,
            slotId: slot.slot_id,
            assetId: selectedAsset?.asset_id ?? workingVersion?.asset_id ?? null,
            versionId: selectedAsset?.version_id ?? workingVersion?.version_id ?? null,
          })}
          prompt={slotPrompt}
          attachments={referenceAttachments}
          libraryOptions={libraryOptions}
          semanticType={slot.slot_type}
          onPromptChange={changeSlotPrompt}
          onRefreshReferences={async () => {
            onLoadVersions?.(slot.slot_id);
            await onRefreshWorkflow?.();
          }}
        />
      ) : (
        <label className="v2-slot-prompt">
          <span>Slot prompt</span>
          <textarea value={slotPrompt} onChange={(event) => changeSlotPrompt(event.target.value)} />
        </label>
      )}
      <V2ReferenceAuditPanel audit={referenceAudit} />
      {workflowId ? (
        <V2ProviderTaskPanel
          workflowId={workflowId}
          slotId={slot.slot_id}
          taskId={providerAudit.provider_task_id}
          isWaiting={slotWaiting}
          refreshSignal={providerTaskRefreshSignal}
          onTerminalRefresh={async () => {
            onLoadVersions?.(slot.slot_id);
            await onRefreshWorkflow?.();
          }}
        />
      ) : null}
      {slot.negative_prompt !== undefined ? (
        <label className="v2-slot-prompt">
          <span>Negative prompt</span>
          <textarea value={negativePrompt} onChange={(event) => changeNegativePrompt(event.target.value)} />
        </label>
      ) : null}
      <button type="button" onClick={() => void savePrompt()}>
        Save slot prompt
      </button>
      {advancedPromptFields.length || providerPromptSnapshot || agentRouteSnapshot || providerPayloadSnapshot ? (
        <details className="v2-slot-advanced-prompts">
          <summary>Advanced prompt and route audit</summary>
          {advancedPromptFields.map(([label, value]) => (
            <label className="v2-slot-prompt" key={label}>
              <span>{label}</span>
              <textarea value={value} readOnly />
            </label>
          ))}
          {providerPromptSnapshot ? (
            <label className="v2-slot-prompt">
              <span>Provider prompt snapshot</span>
              <textarea value={providerPromptSnapshot} readOnly />
            </label>
          ) : null}
          {agentRouteSnapshot ? (
            <pre className="v2-provider-payload-snapshot">{agentRouteSnapshot}</pre>
          ) : null}
          {providerPayloadSnapshot ? (
            <pre className="v2-provider-payload-snapshot">{providerPayloadSnapshot}</pre>
          ) : null}
        </details>
      ) : null}
      {onAttachReference ? (
        <V2ReferencePicker targetType="slot" targetId={slot.slot_id} assets={referenceAssets} onAttach={onAttachReference} />
      ) : null}
      <footer className="v2-slot-history">
        <span>History versions: {versionHistory.length}</span>
        {onLoadVersions ? (
          <button type="button" onClick={() => onLoadVersions(slot.slot_id)}>
            {slotVersions ? "Refresh history" : "View history"}
          </button>
        ) : null}
      </footer>
      {versionHistory.length ? (
        <details className="v2-slot-version-history">
          <summary>History versions</summary>
          <div className="v2-slot-history-list">
            {versionHistory.map((asset) => {
              const isSelected = selectedAsset?.asset_id === asset.asset_id || selectedAsset?.version_id === asset.version_id;
              return (
                <section className="v2-slot-version v2-slot-history-version" key={`${asset.asset_id}:${asset.version_id}`} data-asset-id={asset.asset_id}>
                  <strong>{isSelected ? "Selected version" : "History version"}</strong>
                  <V2AssetVersionPreview asset={asset} label={`${slot.slot_type} history`} />
                  <span>{assetLabel(asset)}</span>
                  {!isSelected ? (
                    <button type="button" onClick={() => onSelectCurrentVersion?.(slot.slot_id, asset.version_id)}>
                      Use this version
                    </button>
                  ) : null}
                </section>
              );
            })}
          </div>
        </details>
      ) : null}
    </article>
  );
}


function formatProviderWarning(value: string | Record<string, unknown>) {
  if (typeof value === "string") return value;
  const code = typeof value.code === "string" ? value.code : "";
  const message = typeof value.message === "string" ? value.message : "";
  return [code, message].filter(Boolean).join(": ") || JSON.stringify(value);
}

function slotReferencesAsAttachments(
  slot: WorkflowSlotV2,
  referenceAssets: Array<{ asset_id: string; version_id?: string | null; display_name?: string; media_type?: string; public_url?: string | null; preview_url?: string | null }>,
): V2SlotAttachment[] {
  const byAssetId = new Map(referenceAssets.map((asset) => [asset.asset_id, asset]));
  return (slot.explicit_reference_ids ?? []).map((assetId) => {
    const asset = byAssetId.get(assetId);
    return {
      relationId: null,
      sourceAssetId: assetId,
      sourceVersionId: asset?.version_id ?? null,
      displayName: asset?.display_name || assetId,
      mediaType: referenceMediaType(asset?.media_type),
      previewUrl: asset?.preview_url ?? asset?.public_url ?? null,
      semanticType: slot.slot_type,
      source: "workflow_asset",
    };
  });
}

function referenceMediaType(value?: string): V2SlotAttachment["mediaType"] {
  return value === "image" || value === "video" || value === "audio" || value === "text" ? value : "unknown";
}

function referenceAuditForSlot(slot: WorkflowSlotV2, runtimeRecord?: RuntimeRecordV2, asset?: AssetVersionV2): Record<string, unknown> | null {
  const slotRecord = slot as WorkflowSlotV2 & {
    reference_audit?: unknown;
    reference_policy?: unknown;
    provider_reference_plan?: unknown;
  };
  return firstRecord(
    slotRecord.reference_audit,
    slotRecord.reference_policy,
    slotRecord.provider_reference_plan,
    recordValue(slot.metadata)?.reference_audit,
    recordValue(asset?.metadata)?.reference_audit,
    recordValue(runtimeRecord?.metadata)?.reference_audit,
  );
}

function firstRecord(...values: unknown[]): Record<string, unknown> | null {
  for (const value of values) {
    const record = recordValue(value);
    if (record) return record;
  }
  return null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}
