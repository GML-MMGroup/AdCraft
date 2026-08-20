import { useEffect, useState } from "react";

import type { GuidedInteractionActionV1 } from "../../../types-v2.ts";

type ConceptChoiceAction = "select" | "custom" | "defer" | "exclude" | "delegate";

const SECONDARY_ACTION_LABELS: Partial<Record<ConceptChoiceAction, string>> = {
  delegate: "Let the Agent choose",
  exclude: "Exclude this stage",
  defer: "Decide later",
};

export function ConceptChoiceSubmitControls({
  allowedActions,
  allowCustom,
  allowExclusion,
  busy,
  selectedOptionId,
  onSubmit,
}: {
  allowedActions: GuidedInteractionActionV1[];
  allowCustom: boolean;
  allowExclusion: boolean;
  busy: boolean;
  selectedOptionId: string | null;
  onSubmit: (action: ConceptChoiceAction, customText: string | null) => void;
}) {
  const canSelect = allowedActions.includes("select");
  const canCustom = allowCustom && allowedActions.includes("custom");
  const secondaryActions = (["delegate", "exclude", "defer"] as const).filter((action) => (
    allowedActions.includes(action)
    && (action !== "exclude" || allowExclusion)
  ));
  const [action, setAction] = useState<ConceptChoiceAction | null>(
    selectedOptionId && canSelect ? "select" : null,
  );
  const [customText, setCustomText] = useState("");

  useEffect(() => {
    if (selectedOptionId && canSelect) setAction("select");
    else setAction((current) => current === "select" ? null : current);
  }, [canSelect, selectedOptionId]);

  const trimmedCustomText = customText.trim();
  const actionAllowed = action === "select"
    ? canSelect
    : action === "custom"
      ? canCustom
      : action !== null && secondaryActions.includes(action as typeof secondaryActions[number]);
  const canSubmit = !busy && actionAllowed && (
    action !== "select" || Boolean(selectedOptionId)
  ) && (
    action !== "custom" || Boolean(trimmedCustomText)
  );

  return (
    <div className="agent-chat__concept-submit">
      {canCustom ? (
        <input
          value={customText}
          disabled={busy}
          placeholder="Describe your direction"
          aria-label="Custom creative direction"
          onFocus={() => setAction("custom")}
          onChange={(event) => {
            setCustomText(event.target.value);
            setAction("custom");
          }}
        />
      ) : null}
      {secondaryActions.length ? (
        <div className="agent-chat__guided-actions" aria-label="Alternative concept actions">
          {secondaryActions.map((candidate) => (
            <button
              type="button"
              key={candidate}
              className={action === candidate ? "is-selected" : ""}
              aria-pressed={action === candidate}
              disabled={busy}
              onClick={() => setAction(candidate)}
            >
              {SECONDARY_ACTION_LABELS[candidate]}
            </button>
          ))}
        </div>
      ) : null}
      <button
        type="button"
        className="agent-chat__concept-submit-button"
        disabled={!canSubmit}
        onClick={() => {
          if (!action || !canSubmit) return;
          onSubmit(action, action === "custom" ? trimmedCustomText : null);
        }}
      >
        {busy ? "Submitting" : "Submit"}
      </button>
    </div>
  );
}
