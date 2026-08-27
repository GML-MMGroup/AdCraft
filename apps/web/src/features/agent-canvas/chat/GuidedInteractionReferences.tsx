import { ImageIcon } from "../../../icons.tsx";
import type { ProposedDraftReferenceV2 } from "../../../types-v2.ts";
import { guidedReferenceKey } from "./guidedInteractionReferences.ts";

export function GuidedInteractionReferences({
  references,
  mediaUrls,
  excludedOptionalReferenceKeys,
  disabled,
  showHeader = true,
  onOptionalReferenceChange,
}: {
  references: ProposedDraftReferenceV2[] | null;
  mediaUrls: Record<string, string>;
  excludedOptionalReferenceKeys: ReadonlySet<string>;
  disabled: boolean;
  showHeader?: boolean;
  onOptionalReferenceChange: (referenceKey: string, accepted: boolean) => void;
}) {
  if (references === null) {
    return (
      <div
        className="agent-chat__guided-reference-loading"
        role="status"
        aria-label="Loading proposal references"
      >
        Loading proposal references...
      </div>
    );
  }
  if (!references.length) return null;

  return (
    <section className="agent-chat__guided-references" aria-label="Proposal references">
      {showHeader ? (
        <header>
          <strong>References</strong>
          <span>{references.length}</span>
        </header>
      ) : null}
      <div className="agent-chat__guided-reference-list">
        {references.map((reference) => {
          const key = guidedReferenceKey(reference);
          const mediaUrl = mediaUrls[key];
          const accepted = reference.required || !excludedOptionalReferenceKeys.has(key);
          return (
            <article key={key}>
              <div className="agent-chat__guided-reference-preview">
                {mediaUrl ? (
                  <img
                    src={mediaUrl}
                    alt={reference.display_name}
                    loading="lazy"
                    decoding="async"
                  />
                ) : <ImageIcon aria-hidden="true" />}
              </div>
              <span>
                <strong>{reference.display_name}</strong>
                <small>
                  {reference.media_type} · {reference.input_role.replaceAll("_", " ")}
                </small>
              </span>
              {reference.required ? (
                <em>Required</em>
              ) : (
                <label>
                  <input
                    type="checkbox"
                    checked={accepted}
                    disabled={disabled}
                    onChange={(event) => onOptionalReferenceChange(key, event.currentTarget.checked)}
                  />
                  Include
                </label>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
