import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function TextWorkbench({
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
      <label className="agent-node-workbench__composer">
        <textarea
          aria-label="Text content"
          value={draft.textContent}
          disabled={draft.pending}
          placeholder="Write the brief, direction, or notes for the next node."
          onChange={(event) => draft.setTextContent(event.currentTarget.value)}
        />
      </label>
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
      <NodeWorkbenchError draft={draft} />
      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div>
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={node.status === "failed" ? "Retry text node" : "Run text node"}
            title={node.status === "failed" ? "Retry text" : "Run text"}
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
