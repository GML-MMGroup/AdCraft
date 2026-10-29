import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../../../i18n/locale.tsx";
import type { CanvasRuntimeSnapshotV2, NodeRuntimeV2 } from "../../../types-v2.ts";
import { ScenePromptFailureNoticeHost } from "./ScenePromptFailureNoticeHost.tsx";
import { scenePromptFailureNotice, type ScenePromptFailureNode } from "./scenePromptFailureNotice.ts";

function scene(overrides: Partial<ScenePromptFailureNode> = {}): ScenePromptFailureNode {
  const error = {
    code: "node_prompt_role_contract_invalid",
    message: "The Scene prompt conflicts with its environment-only role contract.",
    retryable: true,
    role_variant: "scene_board",
    violation_category: "narrative_progression",
    field_path: "generation_prompt",
  };
  return {
    workflow_id: "workflow-1", node_id: "scene-main", creative_role: "scene",
    title: "曜黑静风·极简虚空 Main", status: "failed", error,
    generation_prompt: "无边界的纯黑虚空，无人物。\n\nDeterministic production policy: scene\nProhibited behavior:\n- No people, product, prop interaction, narrative action, or text.",
    latest_attempt: {
      execution_id: "execution-1", member_id: "member-1", run_intent_snapshot_id: null,
      status: "failed", created_at: "2026-10-23T06:14:00Z", updated_at: "2026-10-23T06:14:20Z", error,
    },
    prompt_preparation: null, updated_at: "2026-10-23T06:14:20Z",
    ...overrides,
  };
}

function runtime(node: ScenePromptFailureNode, overrides: Partial<NodeRuntimeV2> = {}): CanvasRuntimeSnapshotV2 {
  return {
    workflow_id: node.workflow_id, active_execution_id: null, execution_status: null,
    queued_node_ids: [], working_node_ids: [], waiting_node_ids: [], ready_node_ids: [], failed_node_ids: [],
    events_cursor: 500, updated_at: "2026-10-23T06:15:00Z",
    node_runtime: { [node.node_id]: {
      node_id: node.node_id, visible_status: "failed", phase: null, execution_id: "execution-1",
      provider_task_id: null, run_intent_snapshot_id: null, parameter_compilation_snapshot_id: null,
      effective_parameters: {}, normalizations: [], omitted_optional_inputs: [],
      waiting_for_node_ids: [], blocked_by_node_ids: [], attempt_no: 0,
      updated_at: "2026-10-23T06:14:20Z", error: node.error, ...overrides,
    } },
  };
}

function host(nodes: ScenePromptFailureNode[], snapshot: CanvasRuntimeSnapshotV2 | null = null, onInspect?: (nodeId: string) => void) {
  return <LocaleProvider initialLocale="zh-CN"><ScenePromptFailureNoticeHost nodes={nodes} runtime={snapshot} onInspect={onInspect} /></LocaleProvider>;
}

const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  window.localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => {
  cleanup();
  for (const [name, descriptor] of [["showModal", originalShowModal], ["close", originalClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});

describe("ScenePromptFailureNoticeHost", () => {
  it("explains the saved Scene failure without exposing codes or blaming the user's creative text", () => {
    render(host([scene()]));
    const dialog = screen.getByRole("alertdialog", { name: "场景生成被提示词校验拦截" });
    expect(dialog.textContent).toContain("曜黑静风·极简虚空 Main");
    expect(dialog.textContent).toContain("“禁止叙事动作”的限制说明误判");
    expect(dialog.textContent).toContain("已完成的内容已保留");
    expect(dialog.textContent).toContain("需要先修正系统对禁止项的识别");
    expect(dialog.textContent).not.toMatch(/node_prompt_role_contract_invalid|narrative_progression|scene_board|generation_prompt|environment-only/);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "知道了" }));
  });

  it("shows a failure arriving through runtime and does not repeat it on snapshot refresh", () => {
    const failed = scene();
    const draft = scene({ status: "draft", error: null, latest_attempt: null, updated_at: "2026-10-23T06:14:00Z" });
    const { rerender } = render(host([draft]));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    rerender(host([draft], runtime(failed)));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
    rerender(host([failed], { ...runtime(failed), events_cursor: 501 }));
    expect(screen.queryByRole("alertdialog")).toBeNull();

    rerender(host([failed], runtime(failed, { execution_id: "execution-2", updated_at: "2026-10-23T06:16:00Z" })));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("opens the affected scene only on the user's action", () => {
    const onInspect = vi.fn();
    render(host([scene()], null, onInspect));
    expect(onInspect).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("button", { name: "知道了" }), { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "查看场景" }));
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "知道了" }));
    fireEvent.click(screen.getByRole("button", { name: "查看场景" }));
    expect(onInspect).toHaveBeenCalledExactlyOnceWith("scene-main");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("dismisses on Escape and shows independent failures one at a time", () => {
    const { rerender } = render(host([scene(), scene({ node_id: "other-scene", title: "第二个场景" })]));
    fireEvent(screen.getByRole("alertdialog"), new Event("cancel", { bubbles: true, cancelable: true }));
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    expect(screen.getByRole("alertdialog").textContent).toContain("第二个场景");
    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
    rerender(host([scene({ workflow_id: "workflow-2" })]));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("removes a resolved failure and ignores stale runtime data or another workflow's snapshot", () => {
    const failed = scene();
    const { rerender } = render(host([failed]));
    rerender(host([failed], runtime(failed, { visible_status: "ready", error: null, updated_at: "2026-10-23T06:16:00Z" })));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    const ready = scene({ status: "ready", error: null, updated_at: "2026-10-23T06:16:00Z" });
    rerender(host([ready], runtime(failed)));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    rerender(host([ready], { ...runtime(failed), workflow_id: "different-workflow" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("does not call unrelated provider or non-Scene failures a Scene validation problem", () => {
    expect(scenePromptFailureNotice(scene({ creative_role: "product" }))).toBeNull();
    expect(scenePromptFailureNotice(scene({ error: { code: "provider_failed", message: "RAW_PROVIDER_ERROR", retryable: true } }))).toBeNull();
  });

  it("uses a general semantic explanation when the system prohibition is not the only narrative match", () => {
    const node = scene({ generation_prompt: `Add narrative action. ${scene().generation_prompt}` });
    render(host([node]));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("未通过纯环境内容检查");
    expect(dialog.textContent).not.toContain("误判");
    expect(dialog.textContent).toContain("仅保留环境、空间布局、光照和材质");
  });
});
