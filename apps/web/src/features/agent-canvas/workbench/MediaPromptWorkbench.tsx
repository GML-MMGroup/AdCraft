import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import { NodeAssetActions } from "./NodeAssetActions.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function MediaPromptWorkbench({
  node,
  draft,
  models,
  modelsLoading,
  modelsError,
  modelResolution,
  onOpenAssets,
  onUploadReferences,
}: {
  node: CanvasNodeV2;
  draft: NodeWorkbenchDraft;
  models: ProviderModelSummaryV1[];
  modelsLoading: boolean;
  modelsError: string | null;
  modelResolution: CanvasRuntimeModelResolutionV2 | null;
  onOpenAssets: () => void;
  onUploadReferences: () => void;
}) {
  const canConfigureProvider = node.status === "draft" || draft.isReadyMedia;

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer">
        <textarea
          aria-label="Generation prompt"
          value={draft.prompt}
          disabled={draft.pending}
          placeholder={`Describe the ${node.node_type} you want to create.`}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
        />
      </label>

      <NodeWorkbenchError draft={draft} />

      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <NodeAssetActions
          disabled={draft.pending}
          showUpload={false}
          onUpload={onUploadReferences}
          onOpenAssets={onOpenAssets}
        />
        <div className="agent-node-workbench__composer-actions">
          {canConfigureProvider ? (
            <div className="agent-node-workbench__options agent-node-workbench__options--inline" aria-label="Generation options">
              <CanvasModelPicker
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
              {node.node_type === "video" ? (
                <label>
                  <span>Duration</span>
                  <input
                    aria-label="Requested video duration"
                    type="number"
                    min="1"
                    step="1"
                    value={typeof draft.parameters.duration_seconds === "number"
                      ? draft.parameters.duration_seconds
                      : ""}
                    disabled={draft.pending}
                    onChange={(event) => {
                      const next = { ...draft.parameters };
                      const duration = Number(event.currentTarget.value);
                      if (
                        event.currentTarget.value
                        && Number.isInteger(duration)
                        && duration > 0
                      ) {
                        next.duration_seconds = duration;
                      } else {
                        delete next.duration_seconds;
                      }
                      delete next.requested_duration_seconds;
                      delete next.effective_duration_seconds;
                      draft.setParameters(next);
                    }}
                  />
                </label>
              ) : null}
            </div>
          ) : null}
          {draft.isReadyMedia ? (
            <button
              type="button"
              className="agent-node-workbench__run"
              aria-label={`Generate ${node.node_type} variation`}
              title="Generate variation"
              disabled={draft.pending || !draft.prompt.trim()}
              onClick={() => void draft.materializeVariation("generate")}
            >
              <SendIcon />
            </button>
          ) : (
            <button
              type="button"
              className="agent-node-workbench__run"
              aria-label={node.status === "failed" ? `Retry ${node.node_type} node` : `Run ${node.node_type} node`}
              title={node.status === "failed" ? "Retry node" : "Run node"}
              disabled={draft.pending || !draft.prompt.trim() || node.status === "working"}
              onClick={() => void draft.run()}
            >
              <SendIcon />
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}
