import { NodeWorkbenchFieldError } from "./NodeWorkbenchFeedback.tsx";
import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2, NodeRuntimeV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { PromptEditor } from "./PromptEditor.tsx";
import { ImageResolutionControls } from "./ImageResolutionControls.tsx";
import { staleImageResolutionParameters } from "./imageResolutionCapabilities.ts";
import { ModelParameterControls } from "./ModelParameterControls.tsx";
import { VideoAudioToggle } from "./VideoAudioToggle.tsx";
import { VideoSubtitleToggle } from "./VideoSubtitleToggle.tsx";
import { mediaExecutionError } from "./mediaExecutionError.ts";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import { NodeAssetActions } from "./NodeAssetActions.tsx";
import { validateModelParameters } from "./modelParameterDescriptors.ts";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import {
  canRetryNodeExecution,
  failureUserAction,
  nodeActionableFailure,
} from "../chat/actionableFailure.ts";
import { useEffect, type RefObject } from "react";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { nodeRunActivity } from "../model/nodeRunActivity.ts";

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
  preparingPrompt = false,
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
  preparingPrompt?: boolean;
}) {
  const t = useTranslation("en-US");
  const canConfigureProvider = ["draft", "failed", "ready", "working"].includes(node.status);
  const selectedModelRef = draft.modelSelectionMode === "explicit"
    ? draft.modelRef
    : (node.node_type === "video" ? defaultModelRef : null)
      ?? node.model_summary?.model_ref ?? modelResolution?.model_ref ?? defaultModelRef;
  const selectedModel = selectedModelRef
    ? models.find((model) => model.model_ref === selectedModelRef) ?? null
    : null;
  const parameterDescriptors = selectedModel?.parameter_descriptors ?? [];
  const resolutionCapabilities = selectedModel?.image_resolution_capabilities ?? null;
  const setDraftParameters = draft.setParameters;
  useEffect(() => {
    if (node.node_type !== "image" || !resolutionCapabilities) return;
    const stale = staleImageResolutionParameters(resolutionCapabilities, draft.parameters);
    if (!stale.length) return;
    const next = { ...draft.parameters };
    stale.forEach((name) => delete next[name]);
    setDraftParameters(next);
  }, [draft.parameters, node.node_type, resolutionCapabilities, setDraftParameters]);
  const audioDescriptor = node.node_type === "video"
    ? parameterDescriptors.find((descriptor) => descriptor.name === "generate_audio" && descriptor.value_type === "boolean")
    : undefined;
  const audioEnabled = typeof draft.parameters.generate_audio === "boolean"
    ? draft.parameters.generate_audio
    : audioDescriptor?.default === true;
  const audioDisabledReason = modelsLoading ? t("Loading model capability")
    : modelsError ? t("Model capability could not be loaded")
      : !canConfigureProvider || !audioDescriptor ? t("The current model does not support audio generation")
        : draft.pending ? t("Submitting, please wait") : null;
  const inlineDescriptors = node.node_type === "video"
    ? VIDEO_TOOLBAR_PARAMETERS.flatMap((name) => parameterDescriptors.filter((descriptor) => descriptor.name === name))
    : [];
  const bodyDescriptors = node.node_type === "video"
    ? parameterDescriptors.filter((descriptor) => !VIDEO_TOOLBAR_PARAMETERS.includes(descriptor.name) && descriptor !== audioDescriptor)
    : parameterDescriptors;
  const parameterIssues = selectedModel && selectedModel.parameter_schema_id
    ? validateModelParameters(parameterDescriptors, draft.parameters, selectedModel.parameter_legal_combinations)
    : [];
  const parametersInvalid = node.node_type !== "image" && parameterIssues.length > 0;
  const combinationIssue = parameterIssues.find((issue) => issue.code === "unsupported_combination");
  const audioIssue = audioDescriptor ? parameterIssues.find((issue) => issue.name === "generate_audio") : undefined;
  const publishing = runtime?.phase === "publishing";
  const executionError = draft.running ? null : mediaExecutionError(node, runtime);
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
    <div className="agent-node-workbench__options agent-node-workbench__options--inline" aria-label={t("Generation options")}>
      <CanvasModelPicker
        appearance={node.node_type !== "audio" ? "monochrome" : "default"}
        showOptionDetails={node.node_type === "audio"}
        showStatusDetails={node.node_type === "audio"}
        defaultModelRef={defaultModelRef}
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
        <PromptEditor
          ariaLabel={t("Generation prompt")}
          value={draft.prompt}
          disabled={draft.pending}
          placeholder={t("Describe the {type} you want to create.", { type: node.node_type })}
          preparing={preparingPrompt}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
          onBlur={() => void draft.flushPrompt()}
          editorRef={promptEditorRef}
        />
      </label>

      {node.node_type === "image" ? (
        draft.error || draft.promptSaveStatus === "conflict" || executionError ? (
          <NodeWorkbenchError draft={draft} executionError={executionError} />
        ) : null
      ) : <NodeWorkbenchError draft={draft} executionError={executionError} />}
      {audioIssue ? (
        <NodeWorkbenchFieldError>
          {t("Generate audio")}: {audioIssue.message}
        </NodeWorkbenchFieldError>
      ) : null}
      {combinationIssue ? (
        <p className="agent-node-workbench__field-error" role="alert">{t("This combination of model parameters is not supported.")}</p>
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
          {node.node_type === "image" && canConfigureProvider && resolutionCapabilities ? (
            <ImageResolutionControls
              layout="inline"
              capabilities={resolutionCapabilities}
              parameters={draft.parameters}
              disabled={draft.pending}
              onChange={draft.setParameters}
            />
          ) : null}
          {node.node_type === "video" ? (
            <div className="agent-node-workbench__video-toggles">
              <VideoAudioToggle
                checked={audioEnabled}
                disabledReason={audioDisabledReason}
                onChange={(enabled) => draft.setParameters({ ...draft.parameters, generate_audio: enabled })}
              />
              <VideoSubtitleToggle
                checked={(draft.parameters.generate_subtitles ?? true) === true}
                disabled={draft.pending || preparingPrompt === true}
                onChange={(enabled) => draft.setParameters({ ...draft.parameters, generate_subtitles: enabled })}
              />
            </div>
          ) : null}
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={retryingExecution
              ? t("Retry {type} node", { type: node.node_type })
              : node.status === "ready" || regenerating
                ? t("Regenerate {type} node", { type: node.node_type })
                : t("Run {type} node", { type: node.node_type })}
            title={retryingExecution ? t("Retry node") : node.status === "ready" || regenerating ? t("Regenerate node") : t("Run node")}
            disabled={draft.pending || publishing || !draft.prompt.trim() || nodeRunActivity(node) !== null || parametersInvalid}
            onClick={() => void draft.run()}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
