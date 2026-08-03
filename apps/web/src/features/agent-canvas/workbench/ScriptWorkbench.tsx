import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
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
  const canRun = node.status === "draft" || node.status === "failed";
  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer agent-node-workbench__composer--script">
        <textarea
          aria-label="Script content"
          value={draft.textContent}
          disabled={draft.pending}
          placeholder="Write or refine the shot-by-shot script."
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
            aria-label={canRun
              ? node.status === "failed" ? "Retry script node" : "Run script node"
              : "Save script node"}
            title={canRun ? node.status === "failed" ? "Retry script" : "Run script" : "Save script"}
            disabled={draft.pending}
            onClick={() => void (canRun ? draft.run() : draft.save())}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
