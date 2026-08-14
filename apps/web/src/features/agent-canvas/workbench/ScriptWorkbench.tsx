import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { CanvasNodeV2, CanvasRuntimeModelResolutionV2 } from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

interface ScriptWorkbenchProps {
  node: CanvasNodeV2;
  draft: NodeWorkbenchDraft;
  models: ProviderModelSummaryV1[];
  modelsLoading: boolean;
  modelsError: string | null;
  modelResolution: CanvasRuntimeModelResolutionV2 | null;
}

export function ScriptWorkbench({
  node,
  draft,
  models,
  modelsLoading,
  modelsError,
  modelResolution,
}: ScriptWorkbenchProps) {
  const isWorking = node.status === "working";

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer">
        <FourLinePromptEditor
          ariaLabel="Script direction"
          value={draft.prompt}
          disabled={draft.pending}
          placeholder="Describe the story, pacing, characters, and scenes for the script."
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
        />
      </label>

      <NodeWorkbenchError draft={draft} />

      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div className="agent-node-workbench__composer-actions">
          <div className="agent-node-workbench__options agent-node-workbench__options--inline" aria-label="Script generation options">
            <CanvasModelPicker
              models={models}
              loading={modelsLoading}
              error={modelsError}
              selectionMode={draft.modelSelectionMode}
              modelRef={draft.modelRef}
              modelSummary={node.model_summary}
              modelResolution={modelResolution}
              disabled={draft.pending || isWorking}
              onChange={draft.setModelSelection}
            />
          </div>
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={node.status === "failed" ? "Retry script node" : "Run script node"}
            title={node.status === "failed" ? "Retry script" : "Run script"}
            disabled={draft.pending || isWorking || !draft.prompt.trim()}
            onClick={() => void draft.run()}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
