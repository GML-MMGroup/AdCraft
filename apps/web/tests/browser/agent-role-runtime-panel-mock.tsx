import { useState } from "react";
import { createRoot } from "react-dom/client";
import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import type {
  AgentCanvasChatTurnV2, AgentCanvasChatViewTimelineV2, AgentCanvasWorkflowV2,
  AgentCapabilityIdV2, ChatCapabilityActivityV2, ChatMessageV2,
} from "../../src/types-v2.ts";
import { AgentCanvasChatPanel } from "../../src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "fixture-role-runtime", project_id: "fixture-role-runtime",
  workflow_schema_version: 2, canvas_model: "agent_canvas_v1", revision: 1,
  layout_revision: 1, nodes: [], bindings: [], assets: [], active_style_skill: null,
};
const roleNames = {
  world_setting: "World Setting", product_design: "Product Designer",
  prop_design: "Prop Designer", character_design: "Character Designer",
  scene_design: "Scene Designer", script_authoring: "Script Writer",
  storyboard_design: "Storyboard Artist", video_direction: "Video Director",
  bgm_direction: "BGM Director", quick_media: "Quick Media",
} satisfies Record<AgentCapabilityIdV2, string>;
const timestamp = "2026-09-06T00:00:00Z";
let attempt = 1;
let revision = 1;
let activities: ChatCapabilityActivityV2[] = [];
let history: ChatCapabilityActivityV2[] = [];
let turns: Record<string, AgentCanvasChatTurnV2> = {};

function makeActivity(capabilityId: AgentCapabilityIdV2, index: number): ChatCapabilityActivityV2 {
  return {
    item_type: "expert_activity", activity_id: `${capabilityId}-${attempt}`,
    turn_id: `turn-${capabilityId}-${attempt}`, capability_id: capabilityId,
    capability_display_name: roleNames[capabilityId], status: "working", sequence: attempt * 100 + index + 3,
    started_at: timestamp, finished_at: null, message: null, error_code: null,
    elapsed_ms: null, attempt_stage: null, retryable: false, validation_paths: [],
    suggested_actions: [], completion_mode: null, warning_code: null,
  };
}
function makeTurn(activity: ChatCapabilityActivityV2): AgentCanvasChatTurnV2 {
  return {
    turn_id: activity.turn_id, workflow_id: workflow.workflow_id, conversation_id: "fixture-conversation",
    status: "running", turn_kind: "capability", request: {}, error_code: null,
    error_message: null, creation_mode: null, guidance_session_revision: null,
    continuation: null, retry_of_turn_id: null, retry_attempt_no: 0, retryable: false,
    operation_stage: "running", operation_failure: null, created_at: timestamp, updated_at: timestamp,
  };
}
function begin(allRoles = false) {
  history = [...history, ...activities.map(activity => {
    if (activity.status !== "working") return activity;
    turns[activity.turn_id] = { ...turns[activity.turn_id]!, status: "superseded", operation_stage: null };
    return { ...activity, status: "superseded" as const, finished_at: timestamp };
  })];
  attempt += 1;
  const capabilities: AgentCapabilityIdV2[] = allRoles
    ? Object.keys(roleNames) as AgentCapabilityIdV2[]
    : ["world_setting", "character_design", "scene_design"];
  activities = capabilities.map(makeActivity);
  turns = { ...turns, ...Object.fromEntries(activities.map(activity => [activity.turn_id, makeTurn(activity)])) };
  if (!allRoles) updateRole("world_setting", "completed");
}
function updateRole(capabilityId: AgentCapabilityIdV2, status: AgentCanvasChatTurnV2["status"], turnOnly = false) {
  activities = activities.map(activity => {
    if (activity.capability_id !== capabilityId) return activity;
    turns[activity.turn_id] = { ...turns[activity.turn_id]!, status,
      operation_stage: status === "running" ? "running" : status === "queued" ? "queued" : null,
      updated_at: timestamp };
    if (turnOnly || status === "queued" || status === "running") return activity;
    return { ...activity, status, finished_at: timestamp };
  });
}
begin();
const messages: ChatMessageV2[] = [
  { item_type: "message", message_kind: "conversation", message_id: "user-1",
    conversation_id: "fixture-conversation", speaker: "user", text: "请同时制作角色和场景。",
    linked_node_ids: [], script_node_id: null, proposal_id: null, capability_id: null,
    sequence: 1, created_at: timestamp },
  { item_type: "message", message_kind: "conversation", message_id: "agent-1",
    conversation_id: "fixture-conversation", speaker: "adcraft_video_agent", text: "角色和场景正在分别制作。",
    linked_node_ids: [], script_node_id: null, proposal_id: null, capability_id: null,
    sequence: 2, created_at: timestamp },
];

// Only this test entry overrides the API boundary. No production hook is mocked.
// Deny every other method, including mutations, so fixture controls cannot write projects.
Object.assign(agentCanvasApi, Object.fromEntries(Object.keys(agentCanvasApi).map(key => [
  key, async () => { throw new Error(`API disabled in deterministic fixture: ${key}`); },
])));
Object.assign(agentCanvasApi, {
  agentCanvasExecutionSettings: async () => ({
    value: { workflow_id: workflow.workflow_id, media_execution_mode: "manual",
      revision: 1, created_at: timestamp, updated_at: timestamp },
    etag: '"fixture-settings-1"',
  }),
  agentCanvasChatTimeline: async (): Promise<AgentCanvasChatViewTimelineV2> => {
    const items = structuredClone([...messages, ...history, ...activities]);
    return {
      workflow_id: workflow.workflow_id, conversation_id: "fixture-conversation",
      guidanceSession: null, guidanceAdvancePrecondition: null, continuations: [],
      current_session_actions: [], items,
      presentationItems: items.map(item => ({
        presentation_key: item.item_type === "message" ? item.message_id : item.activity_id,
        presentation_revision: revision, source_entry_ids: [], message_key: null,
        message_args: {}, response_locale: "zh-CN", item,
      })), next_cursor: items.length,
    };
  },
  agentCanvasChatTurn: async (_workflowId: string, turnId: string) => {
    if (!turns[turnId]) throw new Error(`Unknown fixture turn: ${turnId}`);
    return structuredClone(turns[turnId]);
  },
} satisfies Partial<typeof agentCanvasApi>);

function RuntimePanelFixture() {
  const [chatRevision, setChatRevision] = useState(revision);
  const [mounted, setMounted] = useState(true);
  function refresh(change: () => void) {
    change();
    revision += 1;
    setChatRevision(revision);
  }
  return (
    <main className="runtime-panel-fixture">
      <section className="runtime-panel-fixture__controls">
        <h1>Agent Role · 真实面板接入验收</h1>
        <p>使用正式对话面板、状态投影和动画组件。数据为确定性测试夹具，不连接真实项目。</p>
        <p>右侧 32px 角色图标由各自的活动和 Turn 驱动。全局 Workflow 状态不用于播放判断。</p>
        <button onClick={() => refresh(() => begin())}>New parallel attempt</button>
        <button onClick={() => refresh(() => begin(true))}>Run all ten roles</button>
        <button onClick={() => refresh(() => {
          for (const activity of activities) updateRole(activity.capability_id, "queued", true);
        })}>Queue all roles</button>
        <button onClick={() => refresh(() => {
          const activity = activities.find(item => item.capability_id === "scene_design")!;
          turns[activity.turn_id] = { ...turns[activity.turn_id]!, operation_stage: "provider_waiting" };
        })}>Scene provider waiting</button>
        <button onClick={() => refresh(() => updateRole("scene_design", "completed"))}>Complete Scene</button>
        <button onClick={() => refresh(() => updateRole("scene_design", "failed", true))}>Fail Scene turn only</button>
        <button onClick={() => refresh(() => updateRole("scene_design", "queued", true))}>Queue Scene turn only</button>
        <button onClick={() => refresh(() => updateRole("character_design", "failed"))}>Fail Character</button>
        <button onClick={() => refresh(() => {
          for (const activity of activities) updateRole(activity.capability_id, "completed");
        })}>Complete all</button>
        <button onClick={() => setMounted(value => !value)}>{mounted ? "Unmount panel" : "Mount panel"}</button>
        <output data-testid="fixture-revision">Revision {chatRevision}</output>
      </section>
      {mounted ? <AgentCanvasChatPanel workflow={workflow} chatRevision={chatRevision}
        chatEvents={[]} onFocusNode={() => undefined} /> : null}
    </main>
  );
}
const style = document.createElement("style");
style.textContent = `
  html, body, #root { margin: 0; width: 100%; height: 100%; background: #0a0a0a; color: #f5f5f5; font: 14px system-ui; }
  * { box-sizing: border-box; }
  .runtime-panel-fixture { position: relative; height: 100%; }
  .runtime-panel-fixture__controls { padding: 40px; margin-right: 410px; max-width: 740px; }
  .runtime-panel-fixture__controls p { color: #a3a3a3; line-height: 1.7; }
  .runtime-panel-fixture__controls button { margin: 6px; padding: 10px 14px; border-radius: 8px; background: #202020; border: 1px solid #4a4a4a; color: inherit; cursor: pointer; }
  .runtime-panel-fixture__controls output { display: block; margin: 16px 6px; color: #a3a3a3; }
`;
document.head.append(style);
createRoot(document.getElementById("root")!).render(<RuntimePanelFixture />);
