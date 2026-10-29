import type { ReactNode } from "react";

import { useTranslation } from "../../../i18n/useTranslation";
import type { BrandSummaryExchange } from "./brandFormSummary.ts";
import type { ProposalReply } from "./conversationExchange.ts";
import { GuidedQuestionBubble } from "./GuidedQuestionBubble.tsx";

function UserAnswerBubble({ label, children }: { label: string; children: ReactNode }) {
  return (
    <article className="agent-chat__message agent-chat__message--user agent-chat__guided-answer-bubble" aria-label={label}>
      <div className="agent-chat__message-body">{children}</div>
    </article>
  );
}

export function ProposalReplyBubble({ reply }: { reply: ProposalReply }) {
  const t = useTranslation();
  return (
    <div className="agent-chat__proposal-reply">
      <UserAnswerBubble label={t("Your guided answer")}>
        <strong className="agent-chat__guided-answer-value">
          <span className="agent-chat__exchange-letter">{reply.letter}</span>
          {reply.title}
        </strong>
      </UserAnswerBubble>
    </div>
  );
}

/** Ask first, then append confirmed selections without replacing the question. */
export function BrandSummaryBubbles({ summary }: { summary: BrandSummaryExchange }) {
  const t = useTranslation();
  return (
    <div className="agent-chat__guided-answer-pair" data-brand-summary={summary.stage}>
      <GuidedQuestionBubble label={t(summary.question)} />
      {summary.rows.length > 0 ? (
        <UserAnswerBubble label={t("Your selections")}>
          <small className="agent-chat__selection-heading">{t("Selected")}</small>
          <dl className="agent-chat__selection-list">
            {summary.rows.map((row) => (
              <div key={row.key}>
                <dt>{row.label ? t(row.label) : row.fallbackLabel}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </UserAnswerBubble>
      ) : null}
    </div>
  );
}
