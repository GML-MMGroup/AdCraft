import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2, NodeRuntimeV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { ModelParameterControls } from "./ModelParameterControls.tsx";
import { VideoAudioToggle } from "./VideoAudioToggle.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import { NodeAssetActions } from "./NodeAssetActions.tsx";
import { validateModelParameters } from "./modelParameterDescriptors.ts";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import {
  canRetryNodeExecution,
  failureUserAction,
  nodeActionableFailure,
} from "../chat/actionableFailure.ts";
import type { RefObject } from "react";

const VIDEO_TOOLBAR_PARAMETERS = ["duration_seconds", "resolution", "aspect_ratio"];

export function MediaPromptWorkbench({
  node,
  runtime,
  draft,
  models,
  defaultModelRef,
  modelsLoading,
  modelsError,
  modelResolution,
  onOpenAssets,
  onUploadReferences,
  promptEditorRef,
}: {
  node: CanvasNodeV2;
  runtime: NodeRuntimeV2 | null;
  draft: NodeWorkbenchDraft;
  models: ProviderModelSummaryV1[];
  defaultModelRef: string | null;
  modelsLoading: boolean;
  modelsError: string | null;
  modelResolution: CanvasRuntimeModelResolutionV2 | null;
  onOpenAssets: () => void;
  onUploadReferences: () => void;
  promptEditorRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const canConfigureProvider = ["draft", "failed", "ready", "working"].includes(node.status);
  const selectedModelRef = draft.modelSelectionMode === "explicit"
    ? draft.modelRef
    : (node.node_type === "video" ? defaultModelRef : null)
      ?? node.model_summary?.model_ref ?? modelResolution?.model_ref ?? defaultModelRef;
  const selectedModel = selectedModelRef
    ? models.find((model) => model.model_ref === selectedModelRef) ?? null
    : null;
  const parameterDescriptors = selectedModel?.parameter_descriptors ?? [];
  const audioDescriptor = node.node_type === "video"
    ? parameterDescriptors.find((descriptor) => descriptor.name === "generate_audio" && descriptor.value_type === "boolean")
    : undefined;
  const audioEnabled = typeof draft.parameters.generate_audio === "boolean"
    ? draft.parameters.generate_audio
    : audioDescriptor?.default === true;
  const audioDisabledReason = modelsLoading ? "正在加载模型能力"
    : modelsError ? "模型能力加载失败"
      : !canConfigureProvider || !audioDescriptor ? "当前模型不支持生成音频"
        : draft.pending ? "正在提交，请稍候" : null;
  const inlineDescriptors = node.node_type === "video"
    ? VIDEO_TOOLBAR_PARAMETERS.flatMap((name) => parameterDescriptors.filter((descriptor) => descriptor.name === name))
    : [];
  const bodyDescriptors = node.node_type === "video"
    ? parameterDescriptors.filter((descriptor) => !VIDEO_TOOLBAR_PARAMETERS.includes(descriptor.name) && descriptor !== audioDescriptor)
    : parameterDescriptors;
  const parameterIssues = selectedModel && selectedModel.parameter_schema_id
    ? validateModelParameters(parameterDescriptors, draft.parameters)
    : [];
  const parametersInvalid = node.node_type !== "image" && parameterIssues.length > 0;
  const audioIssue = audioDescriptor ? parameterIssues.find((issue) => issue.name === "generate_audio") : undefined;
  const publishing = runtime?.phase === "publishing";
  const retryingExecution = canRetryNodeExecution(node);
  const regenerating = node.status === "failed"
    && failureUserAction(nodeActionableFailure(node)) === "regenerate";
  const assetActions = (
    <NodeAssetActions
      disabled={draft.pending}
      showUpload={false}
      onUpload={onUploadReferences}
      onOpenAssets={onOpenAssets}
    />
  );

  const modelPicker = canConfigureProvider ? (
    <div className="agent-node-workbench__options agent-node-workbench__options--inline" aria-label="Generation options">
      <CanvasModelPicker
        appearance={node.node_type !== "audio" ? "monochrome" : "default"}
        showOptionDetails={node.node_type === "audio"}
        showStatusDetails={node.node_type !== "image"}
        defaultModelRef={node.node_type !== "audio" ? defaultModelRef : undefined}
        models={models}
        loading={modelsLoading}
        error={modelsError}
        selectionMode={draft.modelSelectionMode}
        modelRef={draft.modelRef}
        modelSummary={node.model_summary}
        modelResolution={modelResolution}
        disabled={draft.pending}
        onChange={draft.setModelSelection}
      />
    </div>
  ) : null;

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer">
        <FourLinePromptEditor
          ariaLabel="Generation prompt"
          value={draft.prompt}
          disabled={draft.pending}
          placeholder={`Describe the ${node.node_type} you want to create.`}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
          onBlur={() => void draft.flushPrompt()}
          editorRef={promptEditorRef}
        />
      </label>

      {node.node_type === "image" ? (
        draft.error || draft.promptSaveStatus === "conflict" ? (
          <div className="agent-node-workbench__image-feedback">
            <NodeWorkbenchError draft={draft} />
          </div>
        ) : null
      ) : <NodeWorkbenchError draft={draft} />}
      {audioIssue ? (
        <p className="agent-node-workbench__field-error">
          Generate audio: {audioIssue.message}
        </p>
      ) : null}

      {node.node_type !== "image" && canConfigureProvider && bodyDescriptors.length ? (
        <ModelParameterControls
          descriptors={bodyDescriptors}
          parameters={draft.parameters}
          disabled={draft.pending}
          onChange={draft.setParameters}
        />
      ) : null}

      <footer className={`agent-node-workbench__footer agent-node-workbench__footer--composer${node.node_type === "image" ? " agent-node-workbench__footer--image" : node.node_type === "video" ? " agent-node-workbench__footer--video" : ""}`}>
        {node.node_type === "video" ? (
          <div className="agent-node-workbench__video-toolbar">
            {assetActions}
            {modelPicker}
            {canConfigureProvider ? (
              <ModelParameterControls
                layout="inline"
                descriptors={inlineDescriptors}
                parameters={draft.parameters}
                disabled={draft.pending}
                onChange={draft.setParameters}
              />
            ) : null}
          </div>
        ) : assetActions}
        <div className="agent-node-workbench__composer-actions">
          {node.node_type !== "video" ? modelPicker : null}
          {node.node_type === "video" ? (
            <VideoAudioToggle
              checked={audioEnabled}
              disabledReason={audioDisabledReason}
              onChange={(enabled) => draft.setParameters({ ...draft.parameters, generate_audio: enabled })}
            />
          ) : null}
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={retryingExecution
              ? `Retry ${node.node_type} node`
              : node.status === "ready" || regenerating
                ? `Regenerate ${node.node_type} node`
                : `Run ${node.node_type} node`}
            title={retryingExecution ? "Retry node" : node.status === "ready" || regenerating ? "Regenerate node" : "Run node"}
            disabled={draft.pending || publishing || !draft.prompt.trim() || node.status === "working" || parametersInvalid}
            onClick={() => void draft.run()}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
