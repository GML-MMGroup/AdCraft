import { SaveIcon } from "../../../icons.tsx";
import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function TextWorkbench({
  node,
  draft,
}: {
  node: CanvasNodeV2;
  draft: NodeWorkbenchDraft;
}) {
  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__title-field">
        <span>Name</span>
        <input
          aria-label="Node title"
          value={draft.title}
          disabled={draft.pending}
          onChange={(event) => draft.setTitle(event.currentTarget.value)}
        />
      </label>
      <label className="agent-node-workbench__composer">
        <span>Text content</span>
        <textarea
          aria-label="Text content"
          value={draft.textContent}
          disabled={draft.pending}
          placeholder="Write the brief, direction, or notes for the next node."
          onChange={(event) => draft.setTextContent(event.currentTarget.value)}
        />
      </label>
      {draft.error ? <p className="agent-node-workbench__error" role="alert">{draft.error}</p> : null}
      <footer className="agent-node-workbench__footer">
        <span>Text is saved as canvas context.</span>
        <button
          type="button"
          className="agent-node-workbench__run"
          aria-label="Save text node"
          title="Save text"
          disabled={draft.pending}
          onClick={() => void draft.save()}
        >
          <SaveIcon />
        </button>
      </footer>
    </div>
  );
}
