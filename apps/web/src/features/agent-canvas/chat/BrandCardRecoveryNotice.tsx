import type { BrandCardRecoveryState } from "./useBrandCardRecovery";

export function BrandCardRecoveryNotice({ state, busy, onRefresh }: {
  state: BrandCardRecoveryState; busy: boolean; onRefresh: () => void;
}) {
  if (state.phase === "review") return null;
  const refreshing = state.phase === "refreshing";
  return <section className="agent-chat__recovery is-interaction" role="alert" aria-label="Brand question needs refreshing" aria-busy={refreshing}>
    <div className="agent-chat__recovery-copy">
      <strong>This Brand question is no longer current</strong>
      <p>Your confirmed decisions are preserved. Refresh the current question, then choose again.</p>
      {busy && !refreshing ? <p>Wait for the current conversation turn to finish.</p> : null}
      {state.error ? <p>{state.error}</p> : null}
    </div>
    <div className="agent-chat__recovery-actions">
      <button type="button" disabled={busy || refreshing} onClick={onRefresh}>
        {refreshing ? "Refreshing question…" : state.needsQuestion ? "Refresh question" : "Reload current question"}
      </button>
    </div>
  </section>;
}
