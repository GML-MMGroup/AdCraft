import { useTranslation } from "../../i18n/useTranslation";
import { useDeferredValue, useMemo, useState } from "react";
import { jsonText } from "../agent-model-call-history";
import { CallDisclosure, RecordedValue } from "./ReadableCallValue";

export function RawCallJson({ request, outcome }: { request: unknown; outcome: unknown }) {
  const t = useTranslation();
  const raw = useMemo(() => jsonText({ request, outcome }), [request, outcome]);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [message, setMessage] = useState("");
  const matches = useMemo(() => {
    if (!deferredQuery) return [];
    return raw.split("\n").flatMap((line, index) => line.toLowerCase().includes(deferredQuery.toLowerCase())
      ? [{ line, number: index + 1 }] : []);
  }, [raw, deferredQuery]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(raw);
      setMessage(t("Full JSON copied"));
    } catch {
      setMessage(t("Copy failed; select and copy the text manually"));
    }
  }
  return <>
    <label>{t("Search raw JSON")}<input value={query} onChange={event => setQuery(event.target.value)} /></label>
    {deferredQuery && <CallDisclosure defaultOpen title={t("Match {count} lines (full JSON is kept below)", { count: matches.length })}>
      <RecordedValue value={matches.map(match => `${match.number}: ${match.line}`).join("\n") || t("No matching content")}/>
    </CallDisclosure>}
    <CallDisclosure defaultOpen title={t("Full request / outcome")}><RecordedValue value={raw}/></CallDisclosure>
    <button type="button" onClick={() => void copy()}>{t("Copy JSON")}</button>
    <span role="status">{message}</span>
  </>;
}
