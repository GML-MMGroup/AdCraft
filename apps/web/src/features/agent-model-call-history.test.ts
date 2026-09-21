import { describe, expect, it, vi, afterEach } from "vitest";
import { extractOutput, normalizeAgentModelCallDetail, normalizeAgentModelCallPage } from "./agent-model-call-history";
import { agentModelCallHistoryApi } from "../api/agentModelCallHistoryApi";
afterEach(() => vi.unstubAllGlobals());
describe("call history contract", () => {
  it("reads actual envelope and preserves incomplete output", () => {
    const detail = normalizeAgentModelCallDetail({ call_id: "c", operation: "plan", started_at: "today", status: "incomplete", request: { payload: { system_prompt: "secret" } }, outcome: null });
    expect(detail.created_at).toBe("today"); expect(detail.outcome).toBeNull(); expect(detail.request?.payload).toEqual({ system_prompt: "secret" });
  });
  it("keeps independent calls from the same run", () => {
    const page = normalizeAgentModelCallPage({ workflow_id: "w", items: [{call_id: "a", run_id: "r", stage: "initial"}, {call_id: "b", run_id: "r", stage: "structured_repair"}], next_offset: 50 });
    expect(page.items).toHaveLength(2); expect(page.next_offset).toBe(50);
  });
  it("extracts SDK chunks and Pi text/tool blocks without duplicating final output", () => {
    expect(extractOutput({ payload: { chunks: [{ choices: [{ delta: { content: "hi" } }] }] } }).text).toBe("hi");
    const output = extractOutput({ payload: { assistant_message: {content: [{type: "text", text: "done"}, {type: "toolCall", name: "submit", arguments: {a: 1}}]}, chunks: ["duplicate"] } });
    expect(output.text).toBe("done"); expect(output.tools).toHaveLength(1);
  });
  it("uses GET, no-store, credentials, abort signal and never internal auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ok: true, json: async () => ({workflow_id: "w", items: [], next_offset: null})}); vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    await agentModelCallHistoryApi.list("w", 50, signal);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/v2/workflows/w/agent-model-calls?offset=50&limit=50", {method: "GET", cache: "no-store", credentials: "same-origin", signal, headers: {Accept: "application/json"}});
  });
  it("does not parse server private error bodies or retry", async () => {
    const json = vi.fn(); const fetchMock = vi.fn().mockResolvedValue({ok:false, status:403, json}); vi.stubGlobal("fetch", fetchMock);
    await expect(agentModelCallHistoryApi.detail("w", "c")).rejects.toThrow("读取权限"); expect(fetchMock).toHaveBeenCalledTimes(1); expect(json).not.toHaveBeenCalled();
  });
});
