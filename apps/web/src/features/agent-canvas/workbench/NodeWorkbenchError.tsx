import { Link } from "react-router-dom";

import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function NodeWorkbenchError({ draft }: { draft: NodeWorkbenchDraft }) {
  if (draft.promptSaveStatus === "conflict") {
    return (
      <div className="agent-node-workbench__error" role="alert">
        <span>This prompt was changed elsewhere. Review the latest workflow before continuing.</span>
        <button
          type="button"
          disabled={draft.pending}
          onClick={() => void draft.retryPromptSave()}
        >
          Retry local prompt
        </button>
        <button
          type="button"
          disabled={draft.pending}
          onClick={() => {
            draft.discardPromptChanges();
            void draft.refreshWorkflow?.();
          }}
        >
          Discard local prompt
        </button>
      </div>
    );
  }
  if (!draft.error) {
    return draft.promptSaveStatus === "saved" && draft.prompt.trim()
      ? <p className="agent-node-workbench__prompt-saved" role="status">Prompt ready · direct-ready</p>
      : null;
  }
  const action = draft.errorAction;
  return (
    <p className="agent-node-workbench__error" role="alert">
      <span>{draft.error}</span>
      {action === "open_api_space" ? <Link to="/api-space">Configure provider</Link> : null}
      {action === "sync_models" ? <Link to="/api-space">Sync models</Link> : null}
      {action === "choose_model" ? <span> Choose a compatible model below.</span> : null}
    </p>
  );
}
