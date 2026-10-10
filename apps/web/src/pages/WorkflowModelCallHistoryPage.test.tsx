import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { WorkflowModelCallHistoryPage } from "./WorkflowModelCallHistoryPage";
import { v2Api } from "../api/v2Client";

const summaries = [
  { call_id: "first-call", run_id: "same-run", workflow_id: "w", operation: "decide_turn_intent", stage: "initial", status: "completed", started_at: "2026-10-08T08:00:00Z" },
  { call_id: "repair-call", run_id: "same-run", workflow_id: "w", operation: "decide_turn_intent", stage: "structured_repair", status: "incomplete" },
];
function setup(outcome: unknown = { payload: { response: { choices: [{ message: { content: '{"assistant_message":"<img src=x onerror=alert(1)>","options":[{"label":"方案 A"}]}' } }] } } }) {
  const fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("?offset=")
    ? { workflow_id: "w", items: summaries, next_offset: null }
    : { ...summaries[url.endsWith("repair-call") ? 1 : 0], request: { payload: { user_prompt: 'User request:\n滑板广告\n\nValidated typed operation context:\n{"recent_messages":[]}', model_ref: "recorded-model", provider: "recorded-provider", effective_timeout_ms: 90000 } }, outcome },
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter initialEntries={["/workflows/w/llm-calls"]}><Routes><Route path="/workflows/:workflowId/llm-calls" element={<WorkflowModelCallHistoryPage/>}/></Routes></MemoryRouter>);
  return fetchMock;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("loads summaries only and keeps retries separate with the same group", async () => {
  const fetchMock = setup();
  const list = screen.getByRole("region", { name: "调用列表" });
  await within(list).findAllByText("理解用户需求");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(within(list).getAllByText("本页第 1 组")).toHaveLength(2);
  expect(within(list).getByText("结构化修复")).toBeTruthy();
  expect(within(list).queryByText("same-run")).toBeNull();
  fireEvent.click(within(list).getAllByRole("button", { name: /理解用户需求/ })[0]);
  await screen.findByText("模型收到了什么");
  expect(screen.getByText("滑板广告")).toBeTruthy();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  expect(document.querySelector(".llm-call-history__detail img")).toBeNull();
  expect(screen.getByText("模型调用完成，不代表结构化校验或整个 Workflow 成功。")).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "调用参数", exact: true }));
  expect(screen.getByText("90000")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "原始 JSON", exact: true }));
  fireEvent.change(screen.getByRole("textbox", { name: "搜索原始 JSON" }), { target: { value: "recorded-model" } });
  await screen.findByText("匹配 1 行（完整 JSON 保留在下方）");
  for (const args of fetchMock.mock.calls as unknown as Array<[string, RequestInit]>) {
    expect(args[1].method).toBe("GET");
    expect(args[1].cache).toBe("no-store");
  }
});

it("does not interpret missing output as running or missing usage as zero", async () => {
  setup(null);
  const rows = await screen.findAllByRole("button", { name: /理解用户需求/ });
  fireEvent.click(rows[1]);
  await screen.findByText("尚未记录到输出，也可能是记录丢失；无法判断是否运行中。");
  expect(screen.getByText("记录不完整，不能据此判断正在生成。")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "错误与完整性", exact: true }));
  expect(screen.getByText("Token 用量：未提供")).toBeTruthy();
  expect(screen.queryByText("校验通过")).toBeNull();
});

it("can expand structured content while leaving its text unmodified", async () => {
  setup();
  fireEvent.click((await screen.findAllByRole("button", { name: /理解用户需求/ }))[0]);
  await screen.findByText("模型返回了什么");
  fireEvent.click(screen.getByText("可选方案 · 1 项"));
  await waitFor(() => expect(screen.getByText("方案 A")).toBeTruthy());
});

it("reads canvas prompts only on demand and reuses one page-scoped read across tabs", async () => {
  const workflowRead = vi.spyOn(v2Api, "workflow").mockResolvedValue({ nodes: [] } as unknown as Awaited<ReturnType<typeof v2Api.workflow>>);
  setup();
  fireEvent.click((await screen.findAllByRole("button", { name: /理解用户需求/ }))[0]);
  await screen.findByText("模型返回了什么");
  expect(workflowRead).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "生成提示词", exact: true }));
  await screen.findByText("当前画布没有已保存的草稿提示词。");
  fireEvent.click(screen.getByRole("button", { name: "概览", exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "生成提示词", exact: true }));
  await screen.findByText("当前画布没有已保存的草稿提示词。");
  expect(workflowRead).toHaveBeenCalledTimes(1);
});
