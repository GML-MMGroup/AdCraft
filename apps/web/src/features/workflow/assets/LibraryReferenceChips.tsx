import type { AssetLibraryEntitySummary } from "../../../types";

export function LibraryReferenceChips({
  entities,
  primaryReferenceIds,
  onRemove,
  onTogglePrimary,
}: {
  entities: AssetLibraryEntitySummary[];
  primaryReferenceIds: Set<string>;
  onRemove: (entityId: string) => void;
  onTogglePrimary: (entity: AssetLibraryEntitySummary) => void;
}) {
  if (!entities.length) return null;
  return (
    <div className="library-reference-chips" aria-label="Selected library references">
      {entities.map((entity) => {
        const sameEntityTypeReferences = entities.filter((item) => item.entity_type === entity.entity_type);
        const canMarkPrimary = sameEntityTypeReferences.length > 1 || entity.entity_type === "character" || entity.entity_type === "scene";
        const primary = primaryReferenceIds.has(entity.entity_id);
        return (
          <span key={entity.entity_id} className={`library-reference-chip ${primary ? "is-primary" : ""}`}>
            <span>{entity.display_name}</span>
            <em>{entity.entity_type}</em>
            {canMarkPrimary ? (
              <button className="library-reference-primary" type="button" aria-pressed={primary} onClick={() => onTogglePrimary(entity)}>
                {primary ? "Primary" : "Set primary"}
              </button>
            ) : null}
            <button type="button" aria-label={`Remove ${entity.display_name}`} onClick={() => onRemove(entity.entity_id)}>
              x
            </button>
          </span>
        );
      })}
    </div>
  );
}
