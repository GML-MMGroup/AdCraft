import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LegacyCallHistoryRedirect, WorkflowModelCallHistoryPage } from "./WorkflowModelCallHistoryPage";
import { agentModelCallHistoryApi as api } from "../api/agentModelCallHistoryApi";
import type { ProjectV2Summary } from "../types-v2";
vi.mock("../api/agentModelCallHistoryApi", () => ({ agentModelCallHistoryApi: { projects: vi.fn(), list: vi.fn(), detail: vi.fn() } }));
function project(id: string): ProjectV2Summary {
  return { project_id: `p-${id}`, workflow_id: id, name: `Project ${id}`, status: "active", is_favorite: false, cover_asset_id: null, project_version: 1, updated_at: "2026-10-12T01:00:00Z" };
}
function HistoryBack() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Back</button>; }
function setup(path = "/logs") {
  return render(<MemoryRouter initialEntries={[path]}><HistoryBack/><Routes>
    <Route path="/logs" element={<WorkflowModelCallHistoryPage/>}/>
    <Route path="/logs/:workflowId" element={<WorkflowModelCallHistoryPage/>}/>
    <Route path="/workflows/:workflowId/llm-calls" element={<LegacyCallHistoryRedirect/>}/>
  </Routes></MemoryRouter>);
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.projects).mockResolvedValue({ items: [project("a"), project("b")], next_cursor: null });
  vi.mocked(api.list).mockImplementation(async workflow_id => ({ workflow_id, items: [{ workflow_id, call_id: `${workflow_id}-call`, run_id: "run", created_at: null, stage: "initial", status: "completed", operation_name: `operation-${workflow_id}` }], next_offset: null }));
  vi.mocked(api.detail).mockImplementation(async (workflow_id, call_id) => ({ workflow_id, call_id, run_id: "run", created_at: null, stage: "initial", status: "completed", operation_name: `operation-${workflow_id}`, request: {}, outcome: null }));
});
afterEach(() => { cleanup(); vi.useRealTimers(); });
it("reads metadata only at /logs, then loads just the chosen workflow and clicked detail", async () => {
  setup(); await screen.findByRole("link", { name: /Project b/ });
  expect(api.list).not.toHaveBeenCalled(); expect(api.detail).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("link", { name: /Project a/ }));
  await screen.findByRole("button", { name: /operation-a/ });
  expect(api.list).toHaveBeenCalledTimes(1); expect(api.detail).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /operation-a/ }));
  await screen.findByText("模型收到了什么");
  fireEvent.click(screen.getByRole("link", { name: /Project b/ }));
  expect(screen.queryByText("模型收到了什么")).toBeNull();
  await screen.findByRole("button", { name: /operation-b/ });
  expect(api.detail).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  await screen.findByRole("button", { name: /operation-a/ });
});
it("supports legacy deep links despite a forbidden project directory", async () => {
  vi.mocked(api.projects).mockRejectedValue(new Error("项目目录无权限"));
  setup("/workflows/unknown/llm-calls");
  await screen.findByRole("button", { name: /operation-unknown/ });
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "项目目录无权限");
  expect(screen.getByRole("link", { name: /当前 Workflow/ }).getAttribute("href")).toBe("/logs/unknown");
});
it("aborts old detail reads and rejects their late results after switching projects", async () => {
  let resolveDetail: (value: Awaited<ReturnType<typeof api.detail>>) => void = () => {};
  vi.mocked(api.detail).mockImplementation(() => new Promise(resolve => { resolveDetail = resolve; }));
  setup("/logs/a");
  fireEvent.click(await screen.findByRole("button", { name: /operation-a/ }));
  const signal = vi.mocked(api.detail).mock.calls[0][2]!;
  fireEvent.click(await screen.findByRole("link", { name: /Project b/ }));
  expect(signal.aborted).toBe(true);
  await act(async () => resolveDetail({ workflow_id: "a", call_id: "old", run_id: null, created_at: null, operation_name: "late-secret", stage: "initial", status: "completed", request: {}, outcome: null }));
  await screen.findByRole("button", { name: /operation-b/ });
  expect(screen.queryByText("late-secret")).toBeNull();
});
it("paginates by server cursor, throttles refresh and resets directory scope", async () => {
  vi.useFakeTimers();
  vi.mocked(api.projects).mockResolvedValueOnce({ items: [project("a")], next_cursor: "opaque-page-2" });
  setup(); await act(() => vi.advanceTimersByTimeAsync(201));
  expect(screen.getByRole("button", { name: "加载更多项目" }).hasAttribute("disabled")).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(2500));
  fireEvent.click(screen.getByRole("button", { name: "加载更多项目" }));
  await act(async () => {});
  expect(vi.mocked(api.projects).mock.calls[1][1]).toBe("opaque-page-2");
  expect(screen.getAllByRole("link", { name: /Project a/ })).toHaveLength(1);
  vi.mocked(api.projects).mockResolvedValue({ items: [project("trash")], next_cursor: null });
  fireEvent.change(screen.getByRole("combobox", { name: "项目范围" }), { target: { value: "trashed" } });
  expect(screen.queryByRole("link", { name: /Project a/ })).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(201));
  expect(vi.mocked(api.projects).mock.calls.at(-1)?.[0]).toBe("trashed");
  expect(screen.getByRole("link", { name: /Project trash/ })).toBeTruthy();
});
it("cancels outstanding requests when the page closes", async () => {
  vi.mocked(api.projects).mockImplementation(() => new Promise(() => {}));
  vi.mocked(api.list).mockImplementation(() => new Promise(() => {}));
  const { unmount } = setup("/logs/a");
  await waitFor(() => expect(api.list).toHaveBeenCalledOnce()); unmount();
  expect(vi.mocked(api.projects).mock.calls[0][2]!.aborted).toBe(true);
  expect(vi.mocked(api.list).mock.calls[0][2]!.aborted).toBe(true);
});
