import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import { SendIcon } from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  CanvasNodeV2,
  CanvasRuntimeModelResolutionV2,
} from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function ScriptWorkbench({
  node,
  status,
  draft,
  models,
  modelsLoading,
  modelsError,
  modelResolution,
}: {
  node: CanvasNodeV2;
  status: CanvasNodeStatusV2;
  draft: NodeWorkbenchDraft;
  models: ProviderModelSummaryV1[];
  modelsLoading: boolean;
  modelsError: string | null;
  modelResolution: CanvasRuntimeModelResolutionV2 | null;
}) {
  const canRun = status === "draft" || status === "failed";
  const isWorking = status === "working";
  const editorDisabled = draft.pending || isWorking;

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer agent-node-workbench__composer--script">
        <FourLinePromptEditor
          ariaLabel={canRun ? "Script prompt" : "Script content"}
          value={canRun ? draft.prompt : draft.textContent}
          disabled={editorDisabled}
          placeholder={canRun
            ? "Describe the script the Script Writer should create."
            : "Write or refine the completed script."}
          onChange={(event) => {
            if (canRun) draft.setPrompt(event.currentTarget.value);
            else draft.setTextContent(event.currentTarget.value);
          }}
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
              disabled={editorDisabled}
              onChange={draft.setModelSelection}
            />
          </div>
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={isWorking
              ? "Script node is working"
              : canRun
              ? status === "failed" ? "Retry script node" : "Run script node"
              : "Save script node"}
            title={isWorking
              ? "Script generation is in progress"
              : canRun
              ? status === "failed" ? "Retry script" : "Run script"
              : "Save script"}
            disabled={editorDisabled}
            onClick={() => void (canRun ? draft.run() : draft.save())}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
