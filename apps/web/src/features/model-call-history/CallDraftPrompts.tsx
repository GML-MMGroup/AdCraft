import { useTranslation } from "../../i18n/useTranslation";
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
  const t = useTranslation();
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
    <h3>{t("Prompts identified in this call")}</h3>
    <p className="llm-call-history__muted">{t("Only recorded prompt fields are shown; they may not have been saved to the canvas.")}</p>
    {Object.keys(prompts).length ? Object.entries(prompts).map(([key, value]) => <section className="llm-call-history__reading" key={key}>
      <h4>{fieldLabel(key)}</h4><ReadableCallValue value={value}/>
    </section>) : <p className="llm-call-history__empty-panel">{t("No prompt fields identified. This call may have asked questions or planned work; check Output and Raw JSON.")}</p>}
    <h3>{t("Prompts currently saved on the canvas")}</h3>
    <p className="llm-call-history__muted">{t("This is the canvas when first read by this page, not a historical snapshot of this call. Reopen this page to update it.")}</p>
    {status === "loading" ? <p>{t("Reading canvas prompts…")}</p> : status === "failed" ? <p role="alert">{t("Canvas prompts could not be read; call records remain available.")}</p> : saved.length ? saved.map(row => <section className="llm-call-history__reading" key={row.key}><h4>{row.title}</h4><ReadableCallValue value={row.value}/></section>) : <p className="llm-call-history__empty-panel">{t("No draft prompts are currently saved on the canvas.")}</p>}
  </>;
}
