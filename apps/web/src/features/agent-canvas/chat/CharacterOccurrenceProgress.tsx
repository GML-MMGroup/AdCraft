import type { GuidedProductionJourneyV2 } from "../../../types-v2.ts";
import { projectCharacterOccurrences } from "./characterOccurrenceProjection.ts";

export function CharacterOccurrenceProgress({
  journey,
}: {
  journey: GuidedProductionJourneyV2;
}) {
  const occurrences = projectCharacterOccurrences(journey);
  if (occurrences.length === 0) return null;

  return (
    <ul className="agent-chat__character-occurrences" aria-label="Character occurrences">
      {occurrences.map((occurrence) => (
        <li
          key={occurrence.occurrenceId}
          className={occurrence.active ? "is-active" : undefined}
          data-testid="character-occurrence"
          data-outcome={occurrence.outcome}
        >
          <span>{occurrence.label}</span>
          {occurrence.summary ? <small>{occurrence.summary}</small> : null}
        </li>
      ))}
    </ul>
  );
}
