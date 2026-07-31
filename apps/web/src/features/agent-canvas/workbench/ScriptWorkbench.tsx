import { PlayIcon, SaveIcon } from "../../../icons.tsx";
import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function ScriptWorkbench({
  node,
  draft,
}: {
  node: CanvasNodeV2;
  draft: NodeWorkbenchDraft;
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
      {draft.error ? <p className="agent-node-workbench__error" role="alert">{draft.error}</p> : null}
      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div>
          <button
            type="button"
            aria-label="Save script node"
            title="Save script"
            disabled={draft.pending}
            onClick={() => void draft.save()}
          >
            <SaveIcon />
          </button>
          {canRun ? (
            <button
              type="button"
              className="agent-node-workbench__run"
              aria-label={node.status === "failed" ? "Retry script node" : "Run script node"}
              title={node.status === "failed" ? "Retry script" : "Run script"}
              disabled={draft.pending}
              onClick={() => void draft.run()}
            >
              <PlayIcon />
            </button>
          ) : null}
        </div>
      </footer>
    </div>
  );
}
