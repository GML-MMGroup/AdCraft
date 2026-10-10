import { useDeferredValue, useMemo, useState } from "react";
import { jsonText } from "../agent-model-call-history";
import { CallDisclosure, RecordedValue } from "./ReadableCallValue";

export function RawCallJson({ request, outcome }: { request: unknown; outcome: unknown }) {
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
      setMessage("已复制完整 JSON");
    } catch {
      setMessage("复制失败，请手动选择文本复制");
    }
  }
  return <>
    <label>搜索原始 JSON <input value={query} onChange={event => setQuery(event.target.value)} /></label>
    {deferredQuery && <CallDisclosure defaultOpen title={`匹配 ${matches.length} 行（完整 JSON 保留在下方）`}>
      <RecordedValue value={matches.map(match => `${match.number}: ${match.line}`).join("\n") || "没有匹配内容"}/>
    </CallDisclosure>}
    <CallDisclosure defaultOpen title="完整 request / outcome"><RecordedValue value={raw}/></CallDisclosure>
    <button type="button" onClick={() => void copy()}>复制 JSON</button>
    <span role="status">{message}</span>
  </>;
}
