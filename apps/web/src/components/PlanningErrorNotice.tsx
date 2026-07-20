import type { PlanningFailureState } from "../pages/homeWorkflowPlanning";

export function PlanningErrorNotice({ error, onRetry }: { error: PlanningFailureState; onRetry: () => void }) {
  const suggestedActions = error.suggestedActions.map(userFacingText).filter((text): text is string => Boolean(text));
  const violations = error.violations.map(userFacingText).filter((text): text is string => Boolean(text));

  return (
    <div className="inline-error" role="alert">
      <p>{error.message}</p>
      {error.stage ? <p>Stage: {error.stage}</p> : null}
      {violations.length ? <ul>{violations.map((violation) => <li key={violation}>{violation}</li>)}</ul> : null}
      {suggestedActions.length ? <ul>{suggestedActions.map((action) => <li key={action}>{action}</li>)}</ul> : null}
      <button className="small-action" type="button" onClick={onRetry}>Retry planning</button>
    </div>
  );
}

function userFacingText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  for (const key of ["label", "message", "detail", "description"]) {
    const text = record[key];
    if (typeof text === "string" && text.trim()) return text;
  }
  return null;
}
