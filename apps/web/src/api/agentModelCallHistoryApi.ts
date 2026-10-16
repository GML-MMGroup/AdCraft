import { normalizeProjectV2ListResponse } from "./v2Normalizers";
import type { ProjectV2Status } from "../types-v2";
import { normalizeAgentModelCallDetail, normalizeAgentModelCallPage } from "../features/agent-model-call-history";

// Browser-facing protected read contract. Never fall back to /internal or attach its token.
async function read(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/v2${path}`, {
    method: "GET", credentials: "same-origin", cache: "no-store", signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "请先登录后查看调用记录。", 403: path.startsWith("/projects?") ? "你没有项目目录读取权限。" : "你没有此 Workflow 的调用日志读取权限。",
      404: "日志读取入口或记录不可用；请确认后端已提供受保护的读取接口。",
      429: "读取过于频繁，请稍后再试。",
    };
    // Do not forward provider payloads or server exception messages into error reporting.
    throw new Error(messages[response.status] ?? "调用记录读取失败，请稍后手动刷新。");
  }
  return response.json();
}
const path = (workflowId: string) => `/workflows/${encodeURIComponent(workflowId)}/agent-model-calls`;
export const agentModelCallHistoryApi = {
  async projects(status: ProjectV2Status, cursor: string | null, signal?: AbortSignal) {
    const query = new URLSearchParams({ status, limit: "50" });
    if (cursor) query.set("cursor", cursor);
    return normalizeProjectV2ListResponse(await read(`/projects?${query}`, signal));
  },
  async list(workflowId: string, offset: number, signal?: AbortSignal) {
    return normalizeAgentModelCallPage(await read(`${path(workflowId)}?offset=${Math.max(0, Math.floor(offset))}&limit=50`, signal));
  },
  async detail(workflowId: string, callId: string, signal?: AbortSignal) {
    return normalizeAgentModelCallDetail(await read(`${path(workflowId)}/${encodeURIComponent(callId)}`, signal));
  },
};
