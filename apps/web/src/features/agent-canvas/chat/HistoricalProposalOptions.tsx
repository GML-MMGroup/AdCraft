import type { CapabilityProposalOptionV2 } from "../../../types-v2.ts";

const OPTION_MARKERS = ["A", "B", "C", "D"] as const;

export function HistoricalProposalOptions({
  options,
  selectedOptionId,
}: {
  options: CapabilityProposalOptionV2[];
  selectedOptionId: string | null;
}) {
  return (
    <div className="agent-chat__historical-options">
      {options.map((option, index) => {
        const selected = option.option_id === selectedOptionId;
        return (
          <article
            key={option.option_id}
            className={`agent-chat__historical-option${selected ? " is-selected" : ""}`}
            aria-label={`${selected ? "Selected option" : "Option"}: ${option.title}`}
          >
            <span className="agent-chat__historical-option-marker" aria-hidden="true">
              {OPTION_MARKERS[index] ?? String(index + 1)}
            </span>
            <span className="agent-chat__historical-option-copy">
              <strong>{option.title}</strong>
              <span>{option.public_summary}</span>
            </span>
          </article>
        );
      })}
    </div>
  );
}
