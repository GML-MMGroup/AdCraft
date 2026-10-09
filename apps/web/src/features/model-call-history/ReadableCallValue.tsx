import { useState, type ReactNode } from "react";
import { jsonText } from "../agent-model-call-history";
import { fieldLabel, parseRecordedJson, recordedEnumLabel } from "./callPresentation";

type CallDisclosureProps = {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  nested?: boolean;
  fieldName?: string;
};

export function CallDisclosure({ title, children, defaultOpen = false, nested = false, fieldName }: CallDisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  return <details open={open} className={`llm-call-history__disclosure${nested ? " llm-call-history__disclosure--nested" : ""}`} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary title={fieldName}>{title}</summary>
    {open ? <div className="llm-call-history__disclosure-body">{children}</div> : null}
  </details>;
}

export function RecordedValue({ value }: { value: unknown }) {
  return <pre className="llm-call-history__value">{value == null ? "未提供" : typeof value === "string" ? value : jsonText(value)}</pre>;
}

/** Plain React text throughout; provider content never becomes HTML or Markdown. */
export function ReadableCallValue({ value, depth = 0, field }: { value: unknown; depth?: number; field?: string }) {
  const parsed = parseRecordedJson(value);
  if (parsed == null) return <p className="llm-call-history__muted">未提供</p>;
  if (typeof parsed !== "object") {
    const text = typeof parsed === "boolean" ? (parsed ? "是（true）" : "否（false）") : String(parsed);
    const label = recordedEnumLabel(field, parsed);
    return <p className="llm-call-history__prose" title={label ? text : undefined}>{label ?? (text === "" ? "空文本" : text)}</p>;
  }
  if (depth >= 4) return <CallDisclosure nested title="展开完整嵌套内容"><RecordedValue value={parsed}/></CallDisclosure>;
  if (Array.isArray(parsed)) {
    if (!parsed.length) return <p className="llm-call-history__muted">空列表（0 项）</p>;
    return <ol className="llm-call-history__readable-list">{parsed.map((item, index) => <li key={index}>
      <ReadableCallValue value={item} depth={depth + 1}/>
    </li>)}</ol>;
  }
  // Put recorded creative content ahead of transport identifiers without changing values.
  const primaryFields = ["assistant_message", "message", "question", "title", "objective", "public_summary", "description", "question_card", "candidates", "step"];
  const priority = (key: string) => {
    const index = primaryFields.indexOf(key);
    return index < 0 ? primaryFields.length : index;
  };
  const entries = Object.entries(parsed).sort(([left], [right]) => priority(left) - priority(right));
  const technicalKeys = new Set(["card_id", "stage_revision", "target_slot_id", "slot_schema_version", "policy_version", "schema_version", "workflow_id", "workflow_revision", "conversation_id", "request_id", "run_id", "call_id", "context_snapshot_id"]);
  const identifiers = entries.filter(([key]) => technicalKeys.has(key));
  if (!entries.length) return <p className="llm-call-history__muted">空对象（0 个字段）</p>;
  return <div className="llm-call-history__fields">{entries.filter(([key]) => !technicalKeys.has(key)).map(([key, child]) => {
    const nested = parseRecordedJson(child);
    return <section className="llm-call-history__field" key={key}>
      {nested && typeof nested === "object" ? <CallDisclosure nested fieldName={key} defaultOpen={depth < 2 && ["question_card", "ordinary_intent", "candidates", "step"].includes(key)} title={`${fieldLabel(key)}${Array.isArray(nested) ? ` · ${nested.length} 项` : ""}`}>
        <ReadableCallValue value={nested} depth={depth + 1}/>
      </CallDisclosure> : <><h4 title={key}>{fieldLabel(key)}</h4><ReadableCallValue value={child} depth={depth + 1} field={key}/></>}
    </section>;
  })}{identifiers.length ? <CallDisclosure nested title={`技术标识与版本 · ${identifiers.length} 项`}><RecordedValue value={Object.fromEntries(identifiers)}/></CallDisclosure> : null}</div>;
}
