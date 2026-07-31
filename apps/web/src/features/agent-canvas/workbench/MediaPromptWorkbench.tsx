import { EditIcon, PlayIcon, SaveIcon, TrashIcon } from "../../../icons.tsx";
import type { CanvasNodeV2, ProviderModelCapabilityV2 } from "../../../types-v2.ts";
import { NodeAssetActions } from "./NodeAssetActions.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function MediaPromptWorkbench({
  node,
  draft,
  capabilities,
  capabilitiesLoading,
  capabilitiesError,
  onOpenAssets,
  onUploadReferences,
}: {
  node: CanvasNodeV2;
  draft: NodeWorkbenchDraft;
  capabilities: ProviderModelCapabilityV2[];
  capabilitiesLoading: boolean;
  capabilitiesError: string | null;
  onOpenAssets: () => void;
  onUploadReferences: () => void;
}) {
  const canConfigureProvider = node.status === "draft" || draft.isReadyMedia;
  const canRun = node.status === "draft" || node.status === "failed";
  const currentModelIsCompatible = !draft.modelId || capabilities.some((item) => item.model_id === draft.modelId);

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer">
        <span>Generation prompt</span>
        <textarea
          aria-label="Generation prompt"
          value={draft.prompt}
          disabled={draft.pending}
          placeholder={`Describe the ${node.node_type} you want to create.`}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
        />
      </label>

      {canConfigureProvider ? (
        <div className="agent-node-workbench__options" aria-label="Generation options">
          <label>
            <span>Model</span>
            <select
              aria-label="Provider model"
              value={draft.modelId}
              disabled={draft.pending || capabilitiesLoading}
              onChange={(event) => draft.setModelId(event.currentTarget.value)}
            >
              <option value="">{capabilitiesLoading ? "Loading models..." : "Automatic"}</option>
              {!currentModelIsCompatible && draft.modelId ? (
                <option value={draft.modelId} disabled>{draft.modelId} (unavailable)</option>
              ) : null}
              {capabilities.filter((item) => item.available).map((item) => (
                <option key={item.model_id} value={item.model_id}>{item.model_id}</option>
              ))}
            </select>
          </label>
          {node.node_type === "video" ? (
            <label>
              <span>Duration</span>
              <input
                aria-label="Requested video duration"
                type="number"
                min="1"
                step="1"
                value={typeof draft.parameters.requested_duration_seconds === "number"
                  ? draft.parameters.requested_duration_seconds
                  : ""}
                disabled={draft.pending}
                onChange={(event) => {
                  const next = { ...draft.parameters };
                  if (event.currentTarget.value) next.requested_duration_seconds = Number(event.currentTarget.value);
                  else delete next.requested_duration_seconds;
                  delete next.effective_duration_seconds;
                  draft.setParameters(next);
                }}
              />
            </label>
          ) : null}
        </div>
      ) : null}
      {capabilitiesError ? <p className="agent-node-workbench__field-error">{capabilitiesError}</p> : null}
      {draft.error ? <p className="agent-node-workbench__error" role="alert">{draft.error}</p> : null}

      {node.node_type === "image" && node.status === "ready" && node.output_asset_id ? (
        <section className="agent-node-workbench__library" aria-label="Save image to My Assets">
          <label>
            <span>Save output to My Assets</span>
            <input
              aria-label="Asset name"
              value={draft.libraryName}
              disabled={draft.pending}
              onChange={(event) => draft.setLibraryName(event.currentTarget.value)}
            />
          </label>
          <select
            aria-label="Asset category"
            value={draft.libraryCategory}
            disabled={draft.pending}
            onChange={(event) => draft.setLibraryCategory(event.currentTarget.value as typeof draft.libraryCategory)}
          >
            <option value="character">Character</option>
            <option value="scene">Scene</option>
            <option value="prop">Prop</option>
          </select>
          <button
            type="button"
            aria-label="Save image to My Assets"
            title="Save to My Assets"
            disabled={draft.pending || !draft.libraryName.trim()}
            onClick={() => void draft.saveImageToLibrary()}
          >
            <SaveIcon />
            <span>{draft.librarySaved ? "Saved" : "Save"}</span>
          </button>
        </section>
      ) : null}

      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <NodeAssetActions
          disabled={draft.pending}
          onUpload={onUploadReferences}
          onOpenAssets={onOpenAssets}
        />
        <div>
          {draft.isReadyMedia ? (
            <>
              <button
                type="button"
                aria-label={`Create ${node.node_type} variation draft`}
                title="Create variation draft"
                disabled={draft.pending || !draft.prompt.trim()}
                onClick={() => void draft.materializeVariation("create_draft")}
              >
                <EditIcon />
              </button>
              <button
                type="button"
                className="agent-node-workbench__run"
                aria-label={`Generate ${node.node_type} variation`}
                title="Generate variation"
                disabled={draft.pending || !draft.prompt.trim()}
                onClick={() => void draft.materializeVariation("generate")}
              >
                <PlayIcon />
              </button>
              {node.variation_draft ? (
                <button
                  type="button"
                  className="agent-node-workbench__danger"
                  aria-label={`Discard ${node.node_type} variation draft`}
                  title="Discard variation draft"
                  disabled={draft.pending}
                  onClick={() => void draft.discardVariation()}
                >
                  <TrashIcon />
                </button>
              ) : null}
            </>
          ) : (
            <>
              <button
                type="button"
                aria-label={`Save ${node.node_type} node`}
                title="Save prompt"
                disabled={draft.pending}
                onClick={() => void draft.save()}
              >
                <SaveIcon />
              </button>
              {canRun ? (
                <button
                  type="button"
                  className="agent-node-workbench__run"
                  aria-label={node.status === "failed" ? `Retry ${node.node_type} node` : `Run ${node.node_type} node`}
                  title={node.status === "failed" ? "Retry node" : "Run node"}
                  disabled={draft.pending || !draft.prompt.trim()}
                  onClick={() => void draft.run()}
                >
                  <PlayIcon />
                </button>
              ) : null}
            </>
          )}
        </div>
      </footer>
    </div>
  );
}
