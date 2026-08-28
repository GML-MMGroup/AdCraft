import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";

const PREPARATION_LABELS = {
  queued: "Preparing generation prompt",
  working: "Preparing generation prompt",
  failed: "Prompt preparation needs attention",
  superseded: "Prompt preparation was replaced",
  ready: "",
} as const;

export function NodePromptPreparationState({ node }: { node: CanvasNodeV2 }) {
  const preparation = promptPreparationForNode(node);
  if (preparation?.status === "ready" || preparation?.status === "not_applicable") return null;

  const summary = node.summary_prompt?.trim() || "Preparing the detailed generation prompt.";
  const status = preparation?.status ?? "queued";
  const error = preparation?.error ?? null;

  return (
    <section
      className={`agent-node-workbench__prompt-preparation is-${status}`}
      role={status === "failed" ? "alert" : "status"}
      aria-label="Prompt preparation status"
    >
      <span>{PREPARATION_LABELS[status]}</span>
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
