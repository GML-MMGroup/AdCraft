import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";

const PREPARATION_LABELS = {
  queued: "Preparing generation prompt",
  working: "Preparing generation prompt",
  failed: "Prompt preparation needs attention",
  ready: "",
} as const;

export function NodePromptPreparationState({ node }: { node: CanvasNodeV2 }) {
  const preparation = promptPreparationForNode(node);
  if (preparation.status === "ready") return null;

  const summary = node.summary_prompt?.trim() || "Preparing the detailed generation prompt.";
  const error = preparation.error;

  return (
    <section
      className={`agent-node-workbench__prompt-preparation is-${preparation.status}`}
      role={preparation.status === "failed" ? "alert" : "status"}
      aria-label="Prompt preparation status"
    >
      <span>{PREPARATION_LABELS[preparation.status]}</span>
      <p>{summary}</p>
      {error ? (
        <small>
          {error.message}
          {error.retryable ? " Retryable." : ""}
        </small>
      ) : null}
    </section>
  );
}
