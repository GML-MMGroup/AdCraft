import { Link } from "react-router-dom";

import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

export function NodeWorkbenchError({ draft }: { draft: NodeWorkbenchDraft }) {
  if (!draft.error) return null;
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
