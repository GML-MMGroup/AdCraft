import type { CapabilityProposalOptionV2 } from "../../../types-v2.ts";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";

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
          <ProposalOptionRow
            key={option.option_id}
            index={index}
            optionId={option.option_id}
            title={option.title}
            summary={option.public_summary}
            selected={selected}
            readOnly
          />
        );
      })}
    </div>
  );
}
