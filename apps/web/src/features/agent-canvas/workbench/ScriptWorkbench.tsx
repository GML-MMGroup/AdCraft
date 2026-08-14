import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import { SendIcon } from "../../../icons.tsx";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function ScriptWorkbench({
  node,
  draft,
  models,
  modelsLoading,
  modelsError,
  modelResolution,
}: {
  node: CanvasNodeV2;
  draft: NodeWorkbenchDraft;
  models: ProviderModelSummaryV1[];
  modelsLoading: boolean;
  modelsError: string | null;
  modelResolution: CanvasRuntimeModelResolutionV2 | null;
}) {
  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer agent-node-workbench__composer--script">
        <FourLinePromptEditor
          ariaLabel="Script content"
          value={draft.textContent}
          disabled={draft.pending}
          placeholder="Write or refine the script for the next production step."
          onChange={(event) => draft.setTextContent(event.currentTarget.value)}
        />
      </label>
      <NodeWorkbenchError draft={draft} />
      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div className="agent-node-workbench__composer-actions">
          <div
            className="agent-node-workbench__options agent-node-workbench__options--inline"
            aria-label="Script generation options"
          >
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
          </div>
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={node.status === "failed" ? "Retry script node" : "Run script node"}
            title={node.status === "failed" ? "Retry script" : "Run script"}
            disabled={draft.pending}
            onClick={() => void draft.run()}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
