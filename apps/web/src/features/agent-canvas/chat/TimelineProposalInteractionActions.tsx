import { useState } from "react";

import { SendIcon } from "../../../icons.tsx";
import type {
  GuidedInteractionActionV1,
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";

const ACTION_LABELS: Record<GuidedInteractionActionV1, string> = {
  answer: "Submit answers",
  select: "Select",
  custom: "Use custom direction",
  skip: "Skip",
  revise: "Revise",
  defer: "Defer",
  exclude: "Exclude",
  delegate: "Delegate",
  accept: "Accept",
  retry: "Retry",
  replace: "Replace",
};

const CONCEPT_ACTIONS = new Set<GuidedInteractionActionV1>([
  "select",
  "custom",
  "revise",
  "defer",
  "exclude",
  "delegate",
]);

export function TimelineProposalInteractionActions({
  acceptedReferences,
  interaction,
  materializationBusy,
  onSubmit,
  pending,
  selectedOptionId,
}: {
  acceptedReferences: ProposedDraftReferenceV2[];
  interaction: GuidedInteractionV1;
  materializationBusy: boolean;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
  pending: boolean;
  selectedOptionId: string | null;
}) {
  const [instruction, setInstruction] = useState("");
  const [instructionAction, setInstructionAction] = useState<"custom" | "revise" | null>(null);
  const actions = interaction.allowed_actions.filter((action) => CONCEPT_ACTIONS.has(action));

  function submit(
    action: "select" | "custom" | "revise" | "defer" | "exclude" | "delegate",
    customValue: string | null = null,
  ) {
    void onSubmit({
      submission_kind: "concept_choice",
      expected_interaction_revision: interaction.revision,
      expected_session_revision: interaction.expected_session_revision,
      action,
      option_id: action === "select" ? selectedOptionId : null,
      custom_value: action === "custom" || action === "revise" ? customValue : null,
      accepted_references: action === "select"
        ? acceptedReferences.map((reference, index) => ({
          source_kind: reference.source_kind,
          source_id: reference.source_id,
          display_name: reference.display_name,
          media_type: reference.media_type,
          binding_kind: reference.binding_kind,
          input_role: reference.input_role,
          required: reference.required,
          display_order: index,
          semantic_reference_role: reference.semantic_reference_role ?? null,
        }))
        : undefined,
    });
  }

  return (
    <>
      <div className="agent-chat__proposal-actions">
        {actions.map((action) => (
          <button
            type="button"
            key={action}
            disabled={pending
              || materializationBusy
              || (action === "select" && !selectedOptionId)}
            onClick={() => {
              if (action === "custom" || action === "revise") {
                setInstructionAction((current) => current === action ? null : action);
                return;
              }
              submit(action as "select" | "defer" | "exclude" | "delegate");
            }}
          >
            {pending ? "Submitting" : ACTION_LABELS[action]}
          </button>
        ))}
      </div>
      {instructionAction ? (
        <form
          className="agent-chat__revision"
          onSubmit={(event) => {
            event.preventDefault();
            const value = instruction.trim();
            if (!value) return;
            submit(instructionAction, value);
            setInstruction("");
            setInstructionAction(null);
          }}
        >
          <input
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="Describe the change"
            aria-label="Proposal revision"
          />
          <button
            type="submit"
            aria-label="Submit proposal revision"
            disabled={!instruction.trim() || pending}
          >
            <SendIcon />
          </button>
        </form>
      ) : null}
    </>
  );
}
