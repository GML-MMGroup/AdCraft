import type { ProductionFocusProjection } from "./productionFocusProjection.ts";

export function CurrentProductionStep({
  focus,
  onViewNodes,
}: {
  focus: ProductionFocusProjection | null;
  onViewNodes: (nodeIds: string[]) => void;
}) {
  if (!focus) return null;
  return (
    <section
      className={`agent-chat__production-step is-${focus.kind}`}
      aria-label="Current production step"
      role="status"
    >
      <div>
        <strong>{focus.title}</strong>
        <span>{focus.detail}</span>
      </div>
      {focus.actionLabel && focus.nodeIds.length ? (
        <button type="button" onClick={() => onViewNodes(focus.nodeIds)}>
          {focus.actionLabel}
        </button>
      ) : null}
    </section>
  );
}
