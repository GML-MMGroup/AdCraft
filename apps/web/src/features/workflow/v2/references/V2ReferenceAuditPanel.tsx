type AuditValue = Record<string, unknown>;

export function V2ReferenceAuditPanel({ audit }: { audit?: AuditValue | null }) {
  if (!audit) return null;
  const acceptedReferences = list(audit.accepted_reference_assets ?? audit.acceptedReferences);
  const promptOnlyReferences = list(audit.prompt_only_reference_assets ?? audit.promptOnlyReferences);
  const rejectedReferences = list(audit.rejected_reference_assets ?? audit.rejectedReferences);
  const warnings = list(audit.warnings);
  const errors = list(audit.errors);
  const fingerprint = audit.prompt_context_fingerprint ?? audit.context_fingerprint ?? audit.fingerprint;
  if (!acceptedReferences.length && !promptOnlyReferences.length && !rejectedReferences.length && !warnings.length && !errors.length && !fingerprint) return null;

  return (
    <details className="v2-reference-audit-panel">
      <summary>Reference audit</summary>
      <ReferenceAuditSection title="Accepted" entries={acceptedReferences} />
      <ReferenceAuditSection title="Used as prompt/context" entries={promptOnlyReferences} />
      <ReferenceAuditSection title="Rejected" entries={rejectedReferences} />
      <ReferenceAuditSection title="Warnings" entries={warnings} />
      <ReferenceAuditSection title="Errors" entries={errors} />
      {fingerprint ? <p>Fingerprint: {text(fingerprint)}</p> : null}
    </details>
  );
}

function ReferenceAuditSection({ title, entries }: { title: string; entries: unknown[] }) {
  if (!entries.length) return null;
  return (
    <section>
      <h4>{title}</h4>
      {entries.map((entry, index) => <pre key={`${title}-${index}`}>{text(entry)}</pre>)}
    </section>
  );
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : JSON.stringify(value, null, 2);
}
