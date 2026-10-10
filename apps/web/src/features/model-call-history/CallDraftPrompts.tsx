import { useEffect, useMemo, useState } from "react";
import type { WorkflowNodeV2 } from "../../types-v2";
import { ReadableCallValue } from "./ReadableCallValue";
import { fieldLabel } from "./callPresentation";

function persistedPromptRows(nodes: WorkflowNodeV2[]) {
  return nodes.flatMap((node) => (node.items ?? []).flatMap((item) => {
    const rows: Array<{ key: string; title: string; value: string }> = [];
    if (item.item_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:item`, title: `${node.title} / ${item.display_name} · item_prompt`, value: item.item_prompt });
    if (item.shot_summary_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:summary`, title: `${node.title} / ${item.display_name} · shot_summary_prompt`, value: item.shot_summary_prompt });
    (item.slots ?? []).forEach((slot) => {
      if (slot.slot_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:${slot.slot_id}:slot`, title: `${node.title} / ${slot.slot_type} · slot_prompt`, value: slot.slot_prompt });
      if (slot.system_suggested_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:${slot.slot_id}:system`, title: `${node.title} / ${slot.slot_type} · system_suggested_prompt`, value: slot.system_suggested_prompt });
      if (slot.user_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:${slot.slot_id}:user`, title: `${node.title} / ${slot.slot_type} · user_prompt`, value: slot.user_prompt });
    });
    return rows;
  }));
}


export function CallDraftPrompts({ readWorkflowNodes, prompts }: { readWorkflowNodes: () => Promise<WorkflowNodeV2[]>; prompts: Record<string, unknown> }) {
  const [nodes, setNodes] = useState<WorkflowNodeV2[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  useEffect(() => {
    let active = true;
    void readWorkflowNodes().then(workflowNodes => {
      if (active) { setNodes(workflowNodes); setStatus("ready"); }
    }).catch(() => { if (active) setStatus("failed"); });
    return () => { active = false; };
  }, [readWorkflowNodes]);
  const saved = useMemo(() => persistedPromptRows(nodes), [nodes]);
  return <>
    <h3>这次调用中识别出的提示词</h3>
    <p className="llm-call-history__muted">仅展示记录中已有的提示词字段，不代表已写入画布。</p>
    {Object.keys(prompts).length ? Object.entries(prompts).map(([key, value]) => <section className="llm-call-history__reading" key={key}>
      <h4>{fieldLabel(key)}</h4><ReadableCallValue value={value}/>
    </section>) : <p className="llm-call-history__empty-panel">未识别到提示词字段。这次调用可能用于提问或规划；也可以在输出和原始 JSON 中核对。</p>}
    <h3>画布当前保存的提示词</h3>
    <p className="llm-call-history__muted">这是本页首次读取到的画布内容，不是本次调用时的历史快照，也不表示全部由本次调用生成。重新打开日志页可更新。</p>
    {status === "loading" ? <p>读取画布提示词…</p> : status === "failed" ? <p role="alert">画布提示词暂时无法读取，调用记录仍可查看。</p> : saved.length ? saved.map(row => <section className="llm-call-history__reading" key={row.key}><h4>{row.title}</h4><ReadableCallValue value={row.value}/></section>) : <p className="llm-call-history__empty-panel">当前画布没有已保存的草稿提示词。</p>}
  </>;
}
