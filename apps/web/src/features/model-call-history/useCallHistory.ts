import { useCallback, useEffect, useRef, useState } from "react";
import { agentModelCallHistoryApi } from "../../api/agentModelCallHistoryApi";
import type { AgentModelCallDetail, AgentModelCallPage } from "../agent-model-call-history";

export const READ_INTERVAL_MS = 2500;
const emptyPage: AgentModelCallPage = { workflow_id: "", items: [], next_offset: null };

/** Local read state only. No workspace context, persistence, polling or production actions. */
export function useCallHistory(workflowId: string) {
  const [page, setPage] = useState(emptyPage);
  const [offsets, setOffsets] = useState([0]);
  const [selected, setSelected] = useState<AgentModelCallDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(false);
  const listRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const nextReadAt = useRef(0);
  const cooldownTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(async (history: number[], initial = false) => {
    if (!workflowId || listRequest.current || (!initial && Date.now() < nextReadAt.current)) return;
    const controller = new AbortController();
    listRequest.current = controller;
    nextReadAt.current = Date.now() + READ_INTERVAL_MS;
    setCooldown(true);
    clearTimeout(cooldownTimer.current);
    cooldownTimer.current = setTimeout(() => setCooldown(false), READ_INTERVAL_MS);
    detailRequest.current?.abort();
    detailRequest.current = null;
    setSelected(null);
    setDetailLoading(false);
    setDetailError(null);
    setLoading(true);
    setError(null);
    try {
      const result = await agentModelCallHistoryApi.list(workflowId, history.at(-1) ?? 0, controller.signal);
      if (controller.signal.aborted) return;
      setPage(result);
      setOffsets(history);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setPage(emptyPage);
        setError(cause instanceof Error ? cause.message : "调用记录读取失败，请手动刷新。");
      }
    } finally {
      if (listRequest.current === controller) listRequest.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    // Collapse React StrictMode's discarded mount without issuing an extra request.
    const timer = setTimeout(() => { void load([0], true); }, 0);
    return () => {
      clearTimeout(timer);
      clearTimeout(cooldownTimer.current);
      listRequest.current?.abort();
      detailRequest.current?.abort();
      listRequest.current = null;
      detailRequest.current = null;
    };
  }, [load]);

  async function select(callId: string) {
    if (listRequest.current || detailRequest.current || selected?.call_id === callId) return;
    const controller = new AbortController();
    detailRequest.current = controller;
    setSelected(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const result = await agentModelCallHistoryApi.detail(workflowId, callId, controller.signal);
      if (!controller.signal.aborted) setSelected(result);
    } catch (cause) {
      if (!controller.signal.aborted) setDetailError(cause instanceof Error ? cause.message : "调用详情读取失败，请重新选择记录。");
    } finally {
      if (detailRequest.current === controller) detailRequest.current = null;
      if (!controller.signal.aborted) setDetailLoading(false);
    }
  }

  const currentOffset = offsets.at(-1) ?? 0;
  return {
    items: page.items, selected, loading, detailLoading, error, detailError, cooldown,
    canPrevious: offsets.length > 1,
    canNext: page.next_offset !== null && page.next_offset > currentOffset,
    refresh: () => load(offsets),
    previous: () => offsets.length > 1 ? load(offsets.slice(0, -1)) : Promise.resolve(),
    next: () => page.next_offset !== null && page.next_offset > currentOffset
      ? load([...offsets, page.next_offset]) : Promise.resolve(),
    select,
  };
}
