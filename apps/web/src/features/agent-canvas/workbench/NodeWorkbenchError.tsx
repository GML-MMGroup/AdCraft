import { Link } from "react-router-dom";

import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import type { CanvasNodeErrorV2 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";

function executionErrorMessage(message: string): string {
  const detail = message.split(/\r?\npayload=/, 1)[0] ?? "";
  if (/\bSetLimitExceeded\b/i.test(detail)) {
    return "The model's usage limit was reached (SetLimitExceeded). Check its usage limit and Safe Experience Mode in the Ark console before running again.";
  }
  const hint = detail.match(/^user_action=(.+)$/m)?.[1]?.trim();
  if (hint) return hint.length > 320 ? `${hint.slice(0, 319)}…` : hint;
  if (/media_api_failed:|\b(?:endpoint|response_body|payload)=/.test(message) || message.length > 500) {
    return "Generation failed. Check the provider settings before running this node again.";
  }
  return message.trim() || "Generation failed.";
}

export function NodeWorkbenchError({ draft, executionError }: {
  draft: NodeWorkbenchDraft;
  executionError?: CanvasNodeErrorV2 | null;
}) {
  const t = useTranslation("en-US");
  if (draft.promptSaveStatus === "conflict") {
    return (
      <div className="agent-node-workbench__error" role="alert">
        <span>{t("This prompt was changed elsewhere. Review the latest workflow before continuing.")}</span>
        <button
          type="button"
          disabled={draft.pending}
          onClick={() => void draft.retryPromptSave()}
        >
          {t("Retry local prompt")}
        </button>
        <button
          type="button"
          disabled={draft.pending}
          onClick={() => {
            draft.discardPromptChanges();
            void draft.refreshWorkflow?.();
          }}
        >
          {t("Discard local prompt")}
        </button>
      </div>
    );
  }
  const message = draft.error ?? (executionError ? executionErrorMessage(executionError.message) : null);
  if (!message) {
    return draft.promptSaveStatus === "saved" && draft.prompt.trim()
      ? <p className="agent-node-workbench__prompt-saved" role="status">{t("Prompt ready · direct-ready")}</p>
      : null;
  }
  const action = draft.error ? draft.errorAction : null;
  return (
    <p className="agent-node-workbench__error" role="alert">
      <span>{message}</span>
      {action === "open_api_space" ? <Link to="/api-space">{t("Configure provider")}</Link> : null}
      {action === "sync_models" ? <Link to="/api-space">{t("Sync models")}</Link> : null}
      {action === "choose_model" ? <span> {t("Choose a compatible model below.")}</span> : null}
    </p>
  );
}
