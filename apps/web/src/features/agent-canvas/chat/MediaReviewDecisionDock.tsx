import { useEffect, useId, useMemo, useState } from "react";

import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { DecisionDockDisclosure, DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

type MediaReviewMode = "accept" | "retry" | "replace" | "exclude";

export interface MediaReviewDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

const MODE_PREFERENCE: MediaReviewMode[] = ["accept", "retry", "replace", "exclude"];

function availableModes(interaction: GuidedInteractionV1): MediaReviewMode[] {
  return MODE_PREFERENCE.filter((action) => interaction.allowed_actions.includes(action));
}

export function MediaReviewDecisionDock({
  interaction,
  pending,
  issue,
  onSubmit,
}: MediaReviewDecisionDockProps) {
  const content = interaction.content.content_kind === "media_review" ? interaction.content : null;
  const modes = useMemo(() => availableModes(interaction), [interaction]);
  const moreId = useId();
  const [mode, setMode] = useState<MediaReviewMode>(() => modes[0] ?? "accept");
  const [instruction, setInstruction] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    if (!modes.includes(mode)) setMode(modes[0] ?? "accept");
  }, [mode, modes]);

  if (!content) return null;

  const replaceReady = mode !== "replace" || Boolean(instruction.trim());
  const submitDisabled = !modes.includes(mode) || !replaceReady;
  const submitLabel = mode === "accept"
    ? "Accept"
    : mode === "retry"
      ? "Retry"
      : mode === "replace"
        ? "Submit replacement"
        : "Confirm exclusion";
  const footerSummary = mode === "accept"
    ? "Accept this result"
    : mode === "retry"
      ? "Generate another result"
      : mode === "replace"
        ? "Describe the replacement"
        : "Exclude this media";

  const submit = () => {
    if (submitDisabled) return;
    const request: GuidedInteractionSubmitRequestV1 = {
      submission_kind: "media_review",
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      action: mode,
      instruction: mode === "replace" ? instruction.trim() : null,
    };
    void onSubmit(request);
  };

  return (
    <DecisionDockFrame
      title={interaction.title}
      context={interaction.context}
      pending={pending}
      issue={issue}
      footerSummary={footerSummary}
      submitLabel={submitLabel}
      submitDisabled={submitDisabled}
      onSubmit={submit}
    >
      <p className="agent-chat__decision-dock-media-summary">{content.summary}</p>

      <div className="agent-chat__decision-dock-secondary-actions" aria-label="Media review actions">
        {modes.includes("retry") ? (
          <button
            type="button"
            disabled={pending}
            aria-pressed={mode === "retry"}
            onClick={() => setMode("retry")}
          >
            Choose Retry
          </button>
        ) : null}
        {modes.includes("replace") ? (
          <button
            type="button"
            disabled={pending}
            aria-pressed={mode === "replace"}
            onClick={() => setMode("replace")}
          >
            Choose Replace
          </button>
        ) : null}
      </div>

      {mode === "replace" ? (
        <label className="agent-chat__decision-dock-inline-input">
          <span>Describe the replacement</span>
          <textarea
            aria-label="Describe the replacement"
            value={instruction}
            disabled={pending}
            onChange={(event) => setInstruction(event.target.value)}
          />
        </label>
      ) : null}

      {modes.includes("exclude") ? (
        <DecisionDockDisclosure
          id={moreId}
          label="More"
          count={null}
          expanded={moreOpen}
          disabled={pending}
          onExpandedChange={setMoreOpen}
        >
          <div className="agent-chat__decision-dock-secondary-actions">
            <button
              type="button"
              disabled={pending}
              aria-pressed={mode === "exclude"}
              onClick={() => setMode("exclude")}
            >
              Exclude this media
            </button>
          </div>
        </DecisionDockDisclosure>
      ) : null}

      {mode === "exclude" ? (
        <div className="agent-chat__decision-dock-confirmation">
          <span>Confirm exclusion before continuing.</span>
          <button type="button" disabled={pending} onClick={() => setMode(modes[0] ?? "accept")}>
            Cancel
          </button>
        </div>
      ) : null}
    </DecisionDockFrame>
  );
}
