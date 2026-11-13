import { useTranslation } from "../../../i18n/useTranslation";
import { BRAND_STAGE_LABELS } from "../brand/brandStageLabels.ts";
import type { BrandSummaryExchange } from "./brandFormSummary.ts";
import type { ProposalReply } from "./conversationExchange.ts";
import { SelectionReceipt } from "./SelectionReceipt.tsx";
import { GuidedQuestionBubble } from "./GuidedQuestionBubble.tsx";

export function ProposalReplyBubble({ reply }: { reply: ProposalReply }) {
  const t = useTranslation();
  return (
    <div className="agent-chat__proposal-reply">
      <SelectionReceipt label={t("Your guided answer")} heading={t("Selected")} value={`${reply.letter} · ${reply.title}`} />
    </div>
  );
}

/** Retain the recorded question alongside its confirmed selections. */
export function BrandSummaryBubbles({ summary, showQuestion = true }: {
  summary: BrandSummaryExchange;
  showQuestion?: boolean;
}) {
  const t = useTranslation();
  return (
    <div className="agent-chat__guided-answer-pair" data-brand-summary={summary.stage}>
      {showQuestion && summary.answer ? <GuidedQuestionBubble label={summary.answer.label} /> : null}
      {summary.rows.length > 0 ? (
        <SelectionReceipt label={t("Your selections")} heading={t("Confirmed")} value={t(BRAND_STAGE_LABELS[summary.stage])}>
          <dl className="agent-chat__selection-list">
            {summary.rows.map((row) => (
              <div key={row.key}>
                <dt>{row.label ? t(row.label) : row.fallbackLabel}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </SelectionReceipt>
      ) : null}
    </div>
  );
}
