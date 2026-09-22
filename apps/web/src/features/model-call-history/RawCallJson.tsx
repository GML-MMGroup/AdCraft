import { useDeferredValue, useMemo, useState } from "react";
import { jsonText } from "../agent-model-call-history";

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
    {deferredQuery && <details open>
      <summary>匹配 {matches.length} 行（完整 JSON 保留在下方）</summary>
      <pre className="llm-call-history__value">{matches.map(match => `${match.number}: ${match.line}`).join("\n") || "没有匹配内容"}</pre>
    </details>}
    <details open><summary>完整 request / outcome</summary><pre className="llm-call-history__value">{raw}</pre></details>
    <button type="button" onClick={() => void copy()}>复制 JSON</button>
    <span role="status">{message}</span>
  </>;
}
