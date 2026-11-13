import type { GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { SelectionReceipt } from "./SelectionReceipt.tsx";
import { BRAND_STAGE_LABELS } from "../brand/brandStageLabels.ts";
import type { BrandStageV2 } from "../brand/brandDecisions.ts";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";
import { GuidedQuestionBubble } from "./GuidedQuestionBubble.tsx";

export function GuidedAnswerBubble({ answer, showQuestion = true }: {
  answer: GuidedAnswerBubbleV1;
  showQuestion?: boolean;
}) {
  const t = useTranslation();
  // The stable Brand interaction ID survives both optimistic submission and history reloads.
  const stage = /_brand_([a-z-]+)_\d+(?:_|$)/.exec(answer.interaction_id)?.[1];
  const stageTitle = stage && Object.hasOwn(BRAND_STAGE_LABELS, stage)
    ? t(stage === "hypothesis" ? "Creative hypothesis" : BRAND_STAGE_LABELS[stage as BrandStageV2])
    : null;
  return (
    <div className="agent-chat__guided-answer-pair" data-guided-answer-id={answer.bubble_id}>
      {showQuestion ? <GuidedQuestionBubble label={answer.label} /> : null}
      <SelectionReceipt label={t("Your guided answer")} heading={t("Selected")} value={stageTitle ?? guidedInteractionCopy(answer.value, t)}>
        {stageTitle
          ? <strong className="agent-chat__selection-receipt-value">{answer.value}</strong>
          : <p>{guidedInteractionCopy(answer.label, t)}</p>}
      </SelectionReceipt>
    </div>
  );
}
