import { SaveIcon, SendIcon } from "../../../icons.tsx";
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
  const isWorldSetting = node.creative_role === "world_setting";

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer">
        <textarea
          aria-label={isWorldSetting ? "World Setting content" : "Text content"}
          value={draft.textContent}
          disabled={draft.pending}
          placeholder={isWorldSetting
            ? "Describe the world, its rules, place, era, and visual continuity."
            : "Write the brief, direction, or notes for the next node."}
          onChange={(event) => draft.setTextContent(event.currentTarget.value)}
        />
      </label>
      {!isWorldSetting ? (
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
      ) : null}
      <NodeWorkbenchError draft={draft} />
      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div>
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={isWorldSetting
              ? "Save World Setting changes"
              : node.status === "failed" ? "Retry text node" : "Run text node"}
            title={isWorldSetting
              ? "Save changes"
              : node.status === "failed" ? "Retry text" : "Run text"}
            disabled={draft.pending}
            onClick={() => void (isWorldSetting ? draft.save() : draft.run())}
          >
            {isWorldSetting ? <SaveIcon /> : <SendIcon />}
          </button>
        </div>
      </footer>
    </div>
  );
}
