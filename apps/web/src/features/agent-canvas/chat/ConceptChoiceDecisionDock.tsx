import { useTranslation } from "../../../i18n/useTranslation";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";
import { useEffect, useRef, useState } from "react";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { BRAND_STAGE_LABELS } from "../brand/brandStageLabels.ts";
import { TREATMENT_STEP_SELECTION_PROMPTS } from "../brand/treatmentStepLabels.ts";
import { isBrandCustomInputCard } from "../model/brandCustomInput.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";

export interface ConceptChoiceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  disabled?: boolean;
  issue: DecisionDockIssue | null;
  selectedOptionId: string | null;
  onSelectOption: (optionId: string) => void;
  onConfirmOption?: () => void;
  onSelectCustom?: () => void;
  onSubmitCustom?: (text: string) => Promise<boolean>;
  /** Display name of the role that proposed the options, used when the context is not user-facing. */
  roleName?: string | null;
  treatmentSubstep?: string | null;
}

// Production proposals carry an internal purpose such as "... Preserve Treatment <sha256>." as
// their context; it is an instruction to the Agent, not a heading for the user.
function isUserFacingContext(context: string | null | undefined): context is string {
  return Boolean(context?.trim()) && !/[0-9a-f]{32,}/i.test(context!);
}

function optionMarker(index: number): string {
  return index < 26 ? String.fromCharCode(65 + index) : String(index + 1);
}

export function ConceptChoiceDecisionDock({
  interaction,
  pending,
  disabled = false,
  issue,
  selectedOptionId,
  onSelectOption,
  onConfirmOption,
  onSelectCustom,
  onSubmitCustom,
  roleName = null,
  treatmentSubstep = null,
}: ConceptChoiceDecisionDockProps) {
  const t = useTranslation("en-US");
  const [customSelected, setCustomSelected] = useState(false);
  const [customText, setCustomText] = useState("");
  const [customSubmitting, setCustomSubmitting] = useState(false);
  const firstOptionIdsByActionRef = useRef(new Map<string, Set<string>>());
  const content = interaction.content.content_kind === "concept_choice" ? interaction.content : null;
  const actionId = content?.action_id ?? null;

  useEffect(() => {
    setCustomSelected(false);
    setCustomText("");
    setCustomSubmitting(false);
  }, [actionId, interaction.revision]);

  if (!content) return null;

  // Brand cards use the generic guided stage; their capability identifies the Brand stage.
  const stageLabel = Object.entries(BRAND_STAGE_LABELS).find(([stage]) => (
    content.capability_id === `brand_${stage}` || content.capability_id.startsWith(`brand_${stage}_`)
  ))?.[1] ?? "Creative direction";
  const treatmentPrompt = treatmentSubstep && (content.capability_id === "brand_treatment"
    || content.capability_id.startsWith("brand_treatment_"))
    ? TREATMENT_STEP_SELECTION_PROMPTS[treatmentSubstep] : null;
  const brandCustomInput = isBrandCustomInputCard(interaction);
  const baselineOptionIds = firstOptionIdsByActionRef.current.get(content.action_id) ?? new Set<string>();
  for (const option of content.options) {
    if (baselineOptionIds.size >= 3) break;
    baselineOptionIds.add(option.option_id);
  }
  firstOptionIdsByActionRef.current.set(content.action_id, baselineOptionIds);
  const customPending = pending || customSubmitting;
  const hasSelection = selectedOptionId !== null || customSelected;
  const canSubmitCustom = Boolean(customText.trim()) && !customPending && !disabled && Boolean(onSubmitCustom);
  const canConfirmOption = !disabled && Boolean(onConfirmOption)
    && interaction.allowed_actions.includes("select")
    && content.options.some((option) => option.option_id === selectedOptionId);

  const submitCustom = async () => {
    const text = customText.trim();
    if (!text || !canSubmitCustom || !onSubmitCustom) return;
    setCustomSubmitting(true);
    try {
      const accepted = await onSubmitCustom(text);
      if (accepted) {
        setCustomSelected(false);
        setCustomText("");
      }
    } finally {
      setCustomSubmitting(false);
    }
  };

  return (
    <DecisionDockFrame
      className={`agent-chat__decision-dock--concept${brandCustomInput ? ` agent-chat__decision-dock--brand-custom-input${content.options.length > 3 ? " is-expanded" : ""}` : ""}`}
      eyebrow={t(stageLabel)}
      meta={t("{count} directions", { count: content.options.length })}
      title={treatmentPrompt
        ? t(treatmentPrompt)
        : content.capability_id === "brand_adspec"
        ? t("Please choose from the following options")
        : isUserFacingContext(interaction.context)
        ? interaction.context
        : roleName
          ? t("{role}: choose a direction", { role: roleName })
          : t("Choose a direction")}
      context={content.capability_id.startsWith("brand_")
        ? t("You can view your selected options in the left panel.") : undefined}
      pending={customPending}
      issue={issue}
      submitLabel={t("Confirm direction")}
      submitDisabled={customSelected ? !canSubmitCustom : !canConfirmOption}
      onSubmit={() => {
        if (customSelected) void submitCustom();
        else onConfirmOption?.();
      }}
    >
      <div className="agent-chat__decision-dock-options" role="radiogroup" aria-label={t("Creative direction options")}>
        {content.options.map((option, index) => (
          <ProposalOptionRow
            key={option.option_id}
            index={index}
            marker={optionMarker(index)}
            selectionRole="radio"
            optionId={option.option_id}
            title={content.capability_id.startsWith("brand_skill-stack") ? guidedInteractionCopy(option.title, t) : option.title}
            summary={content.capability_id.startsWith("brand_skill-stack") ? guidedInteractionCopy(option.summary, t) : option.summary}
            recommended={option.recommended}
            selected={selectedOptionId === option.option_id}
            disabled={customPending || disabled}
            onSelect={() => {
              setCustomSelected(false);
              setCustomText("");
              onSelectOption(option.option_id);
            }}
            badge={brandCustomInput && !hasSelection && !baselineOptionIds.has(option.option_id)
              ? t("New") : undefined}
          />
        ))}
        {brandCustomInput ? (
          <ProposalOptionRow
            index={content.options.length}
            marker={optionMarker(content.options.length)}
            selectionRole="radio"
            optionId="custom"
            custom
            title={t("Other (custom)")}
            summary={t("Write your own idea, or ask for more options")}
            selected={customSelected}
            disabled={customPending || disabled}
            onSelect={() => {
              setCustomSelected(true);
              onSelectCustom?.();
            }}
          />
        ) : null}
      </div>
      {brandCustomInput && customSelected ? (
        <div className="agent-chat__concept-choice-custom-input">
          <label>
            <span>{t("Custom content")}</span>
            <textarea
              aria-label={t("Custom content")}
              maxLength={500}
              placeholder={t("Write your own idea, or ask for more options")}
              value={customText}
              disabled={customPending || disabled}
              onChange={(event) => setCustomText(event.target.value)}
            />
          </label>
        </div>
      ) : null}
    </DecisionDockFrame>
  );
}
