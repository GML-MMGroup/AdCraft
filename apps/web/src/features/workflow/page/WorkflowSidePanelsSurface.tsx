import { AssetMentionInput } from "../../../components/PromptComposer";
import { WorkflowCopilotPanel } from "../../../components/WorkflowCopilotPanel";
import type { DraggablePanelKey, PanelOffset } from "../../../components/WorkflowDraggablePanel";
import type { PromptGenerateContext } from "../../../components/PromptComposer";
import type {
  AdRequest,
  AgentConversationSuggestedAction,
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  CanvasTargetReference,
  ChatNodeReference,
  VideoEditingExportResult,
  WorkflowNode,
  WorkflowVariable,
} from "../../../types.ts";
import type { V2InputAssetUploadItem } from "../../../types-v2.ts";
import type { NodeMentionOption } from "../../../workflow/nodeMentions.ts";
import { LibraryReferenceChips } from "../assets/LibraryReferenceChips.tsx";
import {
  AgentConversationPanel,
  type AgentConversationPanelProps,
  type ConversationActionTarget,
} from "../copilot/AgentConversationPanel.tsx";
import type { FinalCompositionExportSettings } from "../final-composition/useFinalCompositionPageController.ts";
import {
  formatJson,
} from "./workflowPageFormatters.ts";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
type RunPanelSettings = {
  only_missing: boolean;
  force_rerun: boolean;
  run_downstream: boolean;
  download_media: boolean;
  compose_when_ready: boolean;
};

export type WorkflowSidePanelsSurfaceModel = {
  collapsed: boolean;
  agentConversations: AgentConversationPanelProps["conversations"];
  activeConversationId: string | null;
  copilotPanelEvents: AgentConversationPanelProps["events"];
  workflowId?: string | null;
  focusNodeId?: string | null;
  conversationLoading: boolean;
  conversationSending: boolean;
  conversationError?: string | null;
  actionBusyById: AgentConversationPanelProps["actionBusyById"];
  conversationMentionReferences: AssetLibraryReference[];
  conversationNodeReferences: ChatNodeReference[];
  conversationTargetReferences: CanvasTargetReference[];
  conversationNodeMentionOptions: NodeMentionOption[];
  panelOffsets: Record<DraggablePanelKey, PanelOffset>;
  adPanelOpen: boolean;
  workflowPrompt: string;
  workflowPromptMentionReferences: AssetLibraryReference[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  promptPrimaryReferenceIds: string[];
  adRequest: AdRequest;
  videoPanelOpen: boolean;
  exportSettings: FinalCompositionExportSettings;
  exportId: string;
  exportResult: VideoEditingExportResult | null;
  videoTimeline: Record<string, unknown>;
  timelineClipCount: number;
  mediaStatusLabel: string;
  exportVideoUrl: string;
  variablesPanelOpen: boolean;
  workflowVariables: WorkflowVariable[];
  runPanelOpen: boolean;
  selectedNodeId: string;
  visibleCanvasNodes: WorkflowNode[];
  overridePrompt: string;
  overrideMentionReferences: AssetLibraryReference[];
  selectedPlanNodeId?: string | null;
  runSettings: RunPanelSettings;
  workflowRunning: boolean;
  currentNodeRunning: boolean;
  currentWorkflowIsV2: boolean;
  selectedNodeUsesV2InlineRegionEditing: boolean;
  activeV2SlotId?: string | null;
};

export type WorkflowSidePanelsSurfaceActions = {
  uploadV2PromptInputAsset: (file: File) => Promise<V2InputAssetUploadItem[]>;
  setConversationMentionReferences: (references: AssetLibraryReference[]) => void;
  setConversationNodeReferences: (references: ChatNodeReference[]) => void;
  setConversationTargetReferences: (references: CanvasTargetReference[]) => void;
  setCollapsed: StateSetter<boolean>;
  setActiveConversationId: (conversationId: string | null) => void;
  createAgentConversation: () => Promise<unknown> | unknown;
  sendCopilotMessage: (prompt: string, context?: PromptGenerateContext) => Promise<void> | void;
  applyConversationAction: (action: AgentConversationSuggestedAction) => Promise<unknown> | unknown;
  rejectConversationAction: (action: AgentConversationSuggestedAction) => Promise<unknown> | unknown;
  selectConversationActionTarget: (target: ConversationActionTarget) => void;
  commitPanelOffset: (panelKey: DraggablePanelKey, offset: PanelOffset) => void;
  setAdPanelOpen: (value: boolean) => void;
  setWorkflowPrompt: (value: string) => void;
  setWorkflowPromptMentionReferences: (references: AssetLibraryReference[]) => void;
  setPickerTarget: (target: "prompt" | "node" | "revision" | "dynamic-item" | "v2-slot-replace" | null) => void;
  removeLibraryEntityForTarget: (target: "prompt" | "node" | "revision" | "dynamic-item" | "v2-slot-replace", entityId: string) => void;
  togglePrimaryReferenceForTarget: (target: "prompt" | "node" | "revision" | "dynamic-item" | "v2-slot-replace", entity: AssetLibraryEntitySummary) => void;
  runFrontDeskChatOnly: () => Promise<unknown> | unknown;
  planWorkflowFromPanelChat: () => Promise<unknown> | unknown;
  generateWorkflowFromPanelChat: () => Promise<unknown> | unknown;
  setAdRequest: StateSetter<AdRequest>;
  planStructuredWorkflow: () => Promise<unknown> | unknown;
  generateStructuredWorkflow: () => Promise<unknown> | unknown;
  setVideoPanelOpen: (value: boolean) => void;
  setExportSettings: StateSetter<FinalCompositionExportSettings>;
  exportEditedVideo: () => Promise<unknown> | unknown;
  setExportId: (value: string) => void;
  refreshVideoExport: () => Promise<unknown> | unknown;
  setVariablesPanelOpen: (value: boolean) => void;
  addWorkflowVariable: (type: WorkflowVariable["variable_type"]) => void;
  updateWorkflowVariable: (variableId: string, patch: Partial<WorkflowVariable>) => void;
  deleteWorkflowVariable: (variableId: string) => void;
  setSelectedNodeId: (nodeId: string) => void;
  setDetailsOpen: (value: boolean) => void;
  setRunPanelOpen: StateSetter<boolean>;
  setOverridePrompt: (value: string) => void;
  setOverrideMentionReferences: (references: AssetLibraryReference[]) => void;
  setRunSettings: StateSetter<RunPanelSettings>;
  validateBackendGraph: () => Promise<unknown> | unknown;
  runSelectedV2Slot: (slotId?: string) => Promise<unknown> | unknown;
  runNode: (options?: { useRunPanelOverride?: boolean }) => Promise<unknown> | unknown;
  runFromSelected: () => Promise<unknown> | unknown;
};

export function WorkflowSidePanelsSurface({
  model,
  actions,
}: {
  model: WorkflowSidePanelsSurfaceModel;
  actions: WorkflowSidePanelsSurfaceActions;
}) {
  return (
    <>
      <WorkflowCopilotPanel collapsed={model.collapsed}>
        <AgentConversationPanel
          conversations={model.agentConversations}
          activeConversationId={model.activeConversationId}
          events={model.copilotPanelEvents}
          workflowId={model.workflowId}
          focusNodeId={model.focusNodeId}
          loading={model.conversationLoading}
          sending={model.conversationSending}
          error={model.conversationError}
          collapsed={model.collapsed}
          actionBusyById={model.actionBusyById}
          mentionReferences={model.conversationMentionReferences}
          mentionNodeReferences={model.conversationNodeReferences}
          mentionTargetReferences={model.conversationTargetReferences}
          nodeMentionOptions={model.conversationNodeMentionOptions}
          onUploadInputAsset={model.workflowId ? undefined : actions.uploadV2PromptInputAsset}
          onMentionReferencesChange={actions.setConversationMentionReferences}
          onMentionNodeReferencesChange={actions.setConversationNodeReferences}
          onMentionTargetReferencesChange={actions.setConversationTargetReferences}
          onToggleCollapsed={() => actions.setCollapsed((value: boolean) => !value)}
          onSelectConversation={actions.setActiveConversationId}
          onCreateConversation={() => void actions.createAgentConversation()}
          onSendMessage={actions.sendCopilotMessage}
          onApplyAction={(action) => void actions.applyConversationAction(action)}
          onRejectAction={(action) => void actions.rejectConversationAction(action)}
          onSelectActionTarget={actions.selectConversationActionTarget}
        />
      </WorkflowCopilotPanel>

      {model.adPanelOpen ? (
        <div className="ad-workflow-panel">
          <div className="panel-heading">
            <strong>Ad workflow APIs</strong>
            <button className="small-action" onClick={() => actions.setAdPanelOpen(false)}>
              Close
            </button>
          </div>
          <label className="node-config-field">
            <span>Chat prompt</span>
            <AssetMentionInput
              value={model.workflowPrompt}
              mentionReferences={model.workflowPromptMentionReferences}
              workflowId={model.workflowId}
              onChange={(nextValue, nextReferences) => {
                actions.setWorkflowPrompt(nextValue);
                actions.setWorkflowPromptMentionReferences(nextReferences);
              }}
            />
          </label>
          <div className="library-reference-row">
            <button className="pill-btn library-reference-trigger" type="button" onClick={() => actions.setPickerTarget("prompt")}>
              Library reference
            </button>
            <LibraryReferenceChips
              entities={model.promptLibraryEntities}
              primaryReferenceIds={new Set(model.promptPrimaryReferenceIds)}
              onRemove={(entityId) => actions.removeLibraryEntityForTarget("prompt", entityId)}
              onTogglePrimary={(entity) => actions.togglePrimaryReferenceForTarget("prompt", entity)}
            />
          </div>
          <div className="node-action-row">
            <button className="small-action" onClick={() => void actions.runFrontDeskChatOnly()}>
              Chat
            </button>
            <button className="small-action" onClick={() => void actions.planWorkflowFromPanelChat()}>
              Plan from chat
            </button>
            <button className="small-action" onClick={() => void actions.generateWorkflowFromPanelChat()}>
              Generate from chat
            </button>
          </div>
          <label className="node-config-field">
            <span>Product</span>
            <input value={model.adRequest.product_name} onChange={(event) => actions.setAdRequest((current) => ({ ...current, product_name: event.target.value }))} />
          </label>
          <label className="node-config-field">
            <span>Description</span>
            <textarea value={model.adRequest.product_description} onChange={(event) => actions.setAdRequest((current) => ({ ...current, product_description: event.target.value }))} />
          </label>
          <label className="node-config-field">
            <span>Selling point</span>
            <input value={model.adRequest.core_selling_point ?? ""} onChange={(event) => actions.setAdRequest((current) => ({ ...current, core_selling_point: event.target.value }))} />
          </label>
          <label className="node-config-field">
            <span>Audience</span>
            <input value={model.adRequest.target_audience} onChange={(event) => actions.setAdRequest((current) => ({ ...current, target_audience: event.target.value }))} />
          </label>
          <div className="ad-form-grid">
            <label className="node-config-field">
              <span>Duration</span>
              <input
                type="number"
                value={model.adRequest.duration_seconds ?? 30}
                onChange={(event) => actions.setAdRequest((current) => ({ ...current, duration_seconds: Number(event.target.value) }))}
              />
            </label>
            <label className="node-config-field">
              <span>Audio</span>
              <select value={model.adRequest.audio_mode ?? "bgm_only"} onChange={(event) => actions.setAdRequest((current) => ({ ...current, audio_mode: event.target.value as AdRequest["audio_mode"] }))}>
                <option value="none">none</option>
                <option value="bgm_only">bgm only</option>
                <option value="full">full</option>
              </select>
            </label>
            <label className="node-config-field">
              <span>Ratio</span>
              <select value={model.adRequest.aspect_ratio ?? "16:9"} onChange={(event) => actions.setAdRequest((current) => ({ ...current, aspect_ratio: event.target.value as AdRequest["aspect_ratio"] }))}>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
                <option value="1:1">1:1</option>
                <option value="4:3">4:3</option>
                <option value="3:4">3:4</option>
                <option value="21:9">21:9</option>
              </select>
            </label>
            <label className="node-config-field">
              <span>Resolution</span>
              <select value={model.adRequest.output_resolution ?? "480p"} onChange={(event) => actions.setAdRequest((current) => ({ ...current, output_resolution: event.target.value as AdRequest["output_resolution"] }))}>
                <option value="480p">480p</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
              </select>
            </label>
          </div>
          <div className="node-action-row">
            <button className="small-action" onClick={() => void actions.planStructuredWorkflow()}>
              Plan structured
            </button>
            <button className="small-action" onClick={() => void actions.generateStructuredWorkflow()}>
              Generate structured
            </button>
          </div>
        </div>
      ) : null}

      {model.videoPanelOpen ? (
        <div className="video-editing-panel">
          <div className="panel-heading">
            <strong>Video Editing</strong>
            <button className="small-action" onClick={() => actions.setVideoPanelOpen(false)}>
              Close
            </button>
          </div>
          <div className="detail-meta">
            <span>{model.workflowId ?? "No workflow"}</span>
            <span>{model.timelineClipCount} clips</span>
            <span>{model.mediaStatusLabel}</span>
          </div>
          <div className="ad-form-grid">
            <label className="node-config-field">
              <span>Resolution</span>
              <select value={model.exportSettings.resolution} onChange={(event) => actions.setExportSettings((current) => ({ ...current, resolution: event.target.value }))}>
                <option value="480p">480p</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
              </select>
            </label>
            <label className="node-config-field">
              <span>Ratio</span>
              <select value={model.exportSettings.aspect_ratio} onChange={(event) => actions.setExportSettings((current) => ({ ...current, aspect_ratio: event.target.value }))}>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
                <option value="1:1">1:1</option>
                <option value="4:3">4:3</option>
              </select>
            </label>
            <label className="node-config-field">
              <span>FPS</span>
              <input type="number" value={model.exportSettings.fps} onChange={(event) => actions.setExportSettings((current) => ({ ...current, fps: Number(event.target.value) }))} />
            </label>
            <label className="node-config-field">
              <span>Bitrate</span>
              <input value={model.exportSettings.bitrate} onChange={(event) => actions.setExportSettings((current) => ({ ...current, bitrate: event.target.value }))} />
            </label>
          </div>
          <div className="node-action-row">
            <button className="small-action" onClick={() => void actions.exportEditedVideo()}>
              Export video
            </button>
          </div>
          <label className="node-config-field">
            <span>Export ID</span>
            <input value={model.exportId} onChange={(event) => actions.setExportId(event.target.value)} placeholder="export_xxx" />
          </label>
          <div className="node-action-row">
            <button className="small-action" onClick={() => void actions.refreshVideoExport()}>
              Refresh export
            </button>
            {model.exportVideoUrl ? (
              <a className="small-action final-video-link" href={model.exportVideoUrl} target="_blank" rel="noreferrer">
                Open export
              </a>
            ) : null}
          </div>
          {model.exportResult?.error ? <span className="empty-output">{model.exportResult.error}</span> : null}
          <pre className="output-json">{formatJson(model.exportResult ?? model.videoTimeline)}</pre>
        </div>
      ) : null}

      {model.variablesPanelOpen ? (
        <div className="workflow-side-panel variables-panel">
          <div className="panel-heading">
            <strong>Variables</strong>
            <button className="small-action" onClick={() => actions.setVariablesPanelOpen(false)}>
              Close
            </button>
          </div>
          <div className="node-action-row">
            <button className="small-action" onClick={() => actions.addWorkflowVariable("string")}>Text</button>
            <button className="small-action" onClick={() => actions.addWorkflowVariable("resource")}>Resource</button>
            <button className="small-action" onClick={() => actions.addWorkflowVariable("option")}>Option</button>
          </div>
          <div className="variable-list">
            {model.workflowVariables.map((variable) => (
              <div key={variable.variable_id} className="variable-card">
                <input value={variable.name} onChange={(event) => actions.updateWorkflowVariable(variable.variable_id, { name: event.target.value })} />
                <select value={variable.variable_type} onChange={(event) => actions.updateWorkflowVariable(variable.variable_id, { variable_type: event.target.value as WorkflowVariable["variable_type"] })}>
                  <option value="string">string</option>
                  <option value="resource">resource</option>
                  <option value="option">option</option>
                </select>
                <textarea value={variable.description ?? ""} placeholder="Description" onChange={(event) => actions.updateWorkflowVariable(variable.variable_id, { description: event.target.value })} />
                {variable.variable_type === "option" ? (
                  <input
                    value={(variable.options ?? []).join(", ")}
                    placeholder="Options, comma separated"
                    onChange={(event) => actions.updateWorkflowVariable(variable.variable_id, { options: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })}
                  />
                ) : null}
                <input
                  value={typeof variable.value === "string" ? variable.value : ""}
                  placeholder="Default value"
                  onChange={(event) => actions.updateWorkflowVariable(variable.variable_id, { value: event.target.value })}
                />
                <label className="run-toggle">
                  <input type="checkbox" checked={Boolean(variable.required)} onChange={(event) => actions.updateWorkflowVariable(variable.variable_id, { required: event.target.checked })} />
                  <span>Required</span>
                </label>
                <button className="small-action danger" onClick={() => actions.deleteWorkflowVariable(variable.variable_id)}>Delete</button>
              </div>
            ))}
            {!model.workflowVariables.length ? <span className="empty-output">No variables yet.</span> : null}
          </div>
        </div>
      ) : null}

    </>
  );
}
