import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { LocaleProvider } from "../../src/i18n/locale.tsx";
import { LanguageSwitcher } from "../../src/components/LanguageSwitcher.tsx";
import { AgentCanvasChatPanel } from "../../src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx";
import { BrandDecisionPanel } from "../../src/features/agent-canvas/brand/BrandDecisionPanel.tsx";
import { normalizeBrandDecisionPanelV1 } from "../../src/features/agent-canvas/brand/brandDecisionNormalizers.ts";
import type { AgentCanvasWorkflowV2, ChatMessageV2, ChatTimelineItemV2, GuidedInteractionV1, GuidedSessionStateV2 } from "../../src/types-v2.ts";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/agent-canvas-page.css";
import "./conversation-design-preview.css";

type Scene = "choice" | "working" | "confirmed";
// Unimplemented preview controls must never reach a real workflow API.
const originalFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  const url = new URL(input instanceof Request ? input.url : String(input), location.href);
  if (url.pathname.startsWith("/api/")) return Promise.resolve(new Response(
    JSON.stringify({ detail: "此操作未包含在对话设计预览中。" }),
    { status: 501, headers: { "Content-Type": "application/json" } },
  ));
  return originalFetch(input, init);
};
const requestedScene = new URLSearchParams(location.search).get("state");
let scene: Scene = requestedScene === "working" || requestedScene === "confirmed" ? requestedScene : "choice";
const timestamp = "2026-11-10T09:30:00Z";
const workflow: AgentCanvasWorkflowV2 = { workflow_id: "conversation-design-preview", project_id: "conversation-design-preview",
  workflow_schema_version: 2, canvas_model: "agent_canvas_v1", revision: 1, layout_revision: 1, nodes: [], bindings: [], assets: [], active_style_skill: null };
const options = [
  { option_id: "pause", title: "让生活，慢半拍", summary: "从忙碌通勤切入，用喝水的片刻找回自己的节奏。", recommended: true },
  { option_id: "companion", title: "带着日常，去远一点", summary: "串联办公与周末出行，让水杯成为生活里的熟悉陪伴。", recommended: false },
  { option_id: "texture", title: "好设计，不必大声", summary: "借助光影与细节，把产品的质感和实用性自然呈现。", recommended: false },
  { option_id: "ritual", title: "从一杯水开始", summary: "用清晨的小小仪式，为普通的一天打开新的可能。", recommended: false },
].map(option => ({ ...option, difference_tags: [], reference_preview: [] }));
const interaction: GuidedInteractionV1 = {
  workflow_id: workflow.workflow_id, interaction_id: "preview_brand_hypothesis_3_choice", session_id: "preview-session",
  checkpoint_id: "preview-checkpoint", kind: "concept_choice", status: "open", response_locale: "zh-CN",
  expected_session_revision: 3, revision: 1, title: "你更想用哪一种方式，讲述这只水杯的故事？", context: "选择广告的创意方向",
  content: { content_kind: "concept_choice", proposal_id: null, stage: "intake", stage_revision: 3,
    action_id: "preview-direction", occurrence_id: null, capability_id: "brand_hypothesis", allow_custom: true, allow_exclusion: false, options },
  allowed_actions: ["select", "custom"], submit_path: "/preview-only", created_at: timestamp, updated_at: timestamp,
};
let session: GuidedSessionStateV2 = {
  session_id: "preview-session", workflow_id: workflow.workflow_id, status: "active", response_locale: "zh-CN",
  goal: { requested_output: "video", delivery_scope: "generated_media", summary: "随行杯品牌广告", explicit_constraints: { duration_seconds: 30 } },
  creative_authority: null, current_checkpoint: null, narrative_direction: null, element_decisions: [], current_topic_id: null,
  topics: [], active_proposal_id: null, active_style_skill_run_id: null,
  completion: { authoring: "not_ready", delivery: "not_ready", editing_preparation: "not_ready", editing_node_id: null,
    matching_node_ids: [], matching_asset_ids: [], plan_document_id: null, plan_revision: null, preparation_receipt_id: null,
    manifest_revision: null, export_status: "not_started", export_id: null, final_completion_receipt_id: null, final_asset_id: null },
  journey: { policy_version: "fixed_ad_production_v2", stage: "intake", stage_status: "waiting_user", stage_revision: 3,
    decisions: [], active_occurrence_id: null, active_action: null, suspended_action: null, transition_evidence: [] },
  interaction: scene === "choice" ? interaction : null, awaiting: null, revision: 3, updated_at: timestamp,
};
let decisions = normalizeBrandDecisionPanelV1({
  workflow_id: workflow.workflow_id, project_id: workflow.project_id, mode: "brand", brand_name: "日常 · 随行杯",
  journey: { stage: "hypothesis", stage_revision: 3, stage_status: "waiting_user" }, early_skills_confirmed: true,
  slot_values: [
    { slot_id: "brand_product_identity", stage: "brand-memory", value: "轻量随行水杯", kind: "fact", provenance: "user_confirmed", confirmed_at: "2026-11-10T09:30:02Z" },
    { slot_id: "brand_audience", stage: "brand-memory", value: "25–35 岁都市通勤人群", kind: "fact", provenance: "user_confirmed", confirmed_at: "2026-11-10T09:30:02Z" },
    { slot_id: "brand_tone", stage: "brand-memory", value: "简约、自然、有温度", kind: "preference", provenance: "user_confirmed", confirmed_at: "2026-11-10T09:30:02Z" },
    { slot_id: "campaign_goal", stage: "campaign", value: "新品发布，建立品牌认知", kind: "constraint", provenance: "user_confirmed", confirmed_at: "2026-11-10T09:30:04Z" },
    { slot_id: "campaign_duration", stage: "campaign", value: "30 秒", kind: "constraint", provenance: "user_confirmed", confirmed_at: "2026-11-10T09:30:04Z" },
  ],
  open_card: { card_id: "preview-direction", stage: "hypothesis", stage_revision: 3,
    target_slot_id: null, question: interaction.title, options: options.map(option => ({ ...option, label: option.title, why: option.summary })) },
});
function message(id: string, speaker: ChatMessageV2["speaker"], text: string, sequence: number): ChatMessageV2 {
  return { item_type: "message", message_kind: "conversation", message_id: id, conversation_id: "preview-conversation", speaker, text,
    linked_node_ids: [], script_node_id: null, proposal_id: null, capability_id: null, sequence, created_at: `2026-11-10T09:30:${String(sequence).padStart(2, "0")}Z` };
}
const history: ChatTimelineItemV2[] = [
  message("brief", "user", "我想为这款随行杯做一支 30 秒的广告。自然一点，有生活感，不要太像硬广。", 1),
  message("understood", "adcraft_video_agent", "明白。让产品出现在真实的生活里，用一个让人记得住的小瞬间，传达它的价值。", 2),
  message("direction-intro", "adcraft_video_agent", "我整理了四个方向。\n\n更推荐 **「让生活，慢半拍」**：用通勤中的短暂停顿，建立人与产品的情绪联系。", 5),
];
let selectedTitle = options[0].title;
const followups: ChatMessageV2[] = [];
let completionTimer: number | undefined;
let previewEpoch = 0;
function notify() { window.dispatchEvent(new Event("conversation-preview-updated")); }
function setScene(next: Scene, reset = false) {
  window.clearTimeout(completionTimer);
  if (reset) previewEpoch += 1;
  scene = next;
  session = { ...session, revision: session.revision + 1, interaction: next === "choice" ? { ...interaction, expected_session_revision: session.revision + 1 } : null };
  decisions = { ...decisions, selected_hypothesis_id: next === "choice" ? null : "selected",
    open_card: next === "choice" ? { card_id: "preview-direction", stage: "hypothesis", stage_revision: 3,
      target_slot_id: null, question: interaction.title, options: options.map(option => ({ ...option, label: option.title, why: option.summary })) } : null,
    hypotheses: next === "choice" ? [] : [{ candidate_id: "selected", label: selectedTitle, insight: "忙碌生活中，每个人都需要属于自己的片刻。", mechanism: "快节奏与短暂停顿的反差", hypothesis: selectedTitle, product_role: "让人慢下来的日常陪伴", hook_mechanism: "城市噪声中的安静一口", why: "把产品功能转化为可感知的生活价值。" }] };
  notify();
}
setScene(scene);
function timeline(): ChatTimelineItemV2[] {
  const items = [...history];
  if (scene !== "choice") {
    items.push({ ...message("selected", "user", selectedTitle, 6), metadata: {
      presentation_kind: "guided_answer", schema_version: 1, submission_id: "preview-submission",
      interaction_id: interaction.interaction_id, answers: [{ question_id: "preview-direction", label: interaction.title, value: selectedTitle }],
    } });
  }
  if (scene !== "choice") items.push({
    item_type: "expert_activity", activity_id: "preview-writing", turn_id: "preview-turn", capability_id: "script_authoring",
    capability_display_name: "脚本设计", status: scene === "working" ? "working" : "completed", sequence: 7, started_at: timestamp,
    finished_at: scene === "working" ? null : "2026-11-10T09:30:08Z",
    message: scene === "working" ? "正在细化故事节奏与产品出场方式。" : "故事节奏已整理完成。",
    error_code: null, elapsed_ms: null, attempt_stage: null, retryable: false, validation_paths: [], suggested_actions: [], completion_mode: null, warning_code: null,
  });
  if (scene === "confirmed") items.push(message("result", "adcraft_video_agent", `**「${selectedTitle}」已确定。**\n\n开场从人潮中的匆忙脚步切入，镜头跟随主角停下、拧开杯盖。环境声渐弱，留下喝水的声音。\n\n### 故事节奏\n- **前 5 秒**：快节奏的城市通勤，建立情境。\n- **中间 20 秒**：一口水让节奏慢下来，自然带出产品细节。\n- **最后 5 秒**：回到生活，留下品牌记忆。\n\n接下来可以细化开场钩子和故事结构。`, 8));
  return [...items, ...followups];
}
Object.assign(agentCanvasApi, {
  agentCanvasExecutionSettings: async () => ({ etag: '"preview"', value: { workflow_id: workflow.workflow_id, media_execution_mode: "manual", revision: 1, created_at: timestamp, updated_at: timestamp } }),
  listAgentCanvasDocuments: async () => ({ workflow_id: workflow.workflow_id, items: [], next_cursor: null }),
  listAgentCanvasPresentationStreams: async () => ({ workflow_id: workflow.workflow_id, streams: [] }),
  agentCanvasCreativeSession: async () => session,
  agentCanvasChatTimeline: async () => ({ workflow_id: workflow.workflow_id, conversation_id: "preview-conversation", guidanceSession: session,
    guidanceAdvancePrecondition: null, continuations: [], current_session_actions: [], presentationItems: null, items: timeline(), next_cursor: 20 }),
  agentCanvasChatTurn: async (_workflowId, turnId) => ({ turn_id: turnId, workflow_id: workflow.workflow_id, conversation_id: "preview-conversation",
    status: scene === "working" ? "running" : "completed", turn_kind: "capability", request: {}, error_code: null, error_message: null,
    creation_mode: null, guidance_session_revision: null, continuation: null, retry_of_turn_id: null, retry_attempt_no: 0, retryable: false,
    operation_stage: scene === "working" ? "running" : null, operation_failure: null, created_at: timestamp, updated_at: timestamp }),
  brandDecisions: async () => decisions,
  brandNextQuestion: async () => null,
  submitAgentCanvasGuidedInteraction: async (_workflowId, _interactionId, request) => {
    if (request.submission_kind !== "concept_choice") throw new Error("Expected a direction");
    selectedTitle = options.find(option => option.option_id === request.option_id)?.title ?? request.custom_text ?? "自定义方向";
    await new Promise(resolve => window.setTimeout(resolve, 450));
    setScene("working");
    completionTimer = window.setTimeout(() => setScene("confirmed"), 3200);
    return { workflow_id: workflow.workflow_id, interaction_id: interaction.interaction_id, submission_id: "preview-submission", receipt_id: "preview-receipt",
      created_node_ids: [], created_binding_ids: [], document_revisions: {}, continuation_id: null, automatic_run_command_ids: [],
      resulting_session_revision: session.revision, events_cursor: 6, replayed: false };
  },
  submitAgentCanvasChatMessage: async (_workflowId, request) => {
    const sequence = 20 + followups.length;
    followups.push(message(`followup-${sequence}`, "user", request.text, sequence));
    followups.push(message(`reply-${sequence}`, "adcraft_video_agent", "这是一段设计预览。你的输入已保留在当前页面，可以继续切换状态，查看对话和方案的呈现效果。", sequence + 1));
    notify();
    return { workflow_id: workflow.workflow_id, conversation_id: "preview-conversation", message_id: `followup-${sequence}`, turn_id: `turn-${sequence}`, status: "queued", events_cursor: sequence + 1,
      retry_of_turn_id: null, retry_attempt_no: 0, replayed: false, presentation_stream_id: null };
  },
} satisfies Partial<typeof agentCanvasApi>);

function Preview() {
  const [revision, setRevision] = useState(0);
  useEffect(() => { const update = () => setRevision(value => value + 1); window.addEventListener("conversation-preview-updated", update); return () => window.removeEventListener("conversation-preview-updated", update); }, []);
  return <div className="conversation-preview">
    <header className="conversation-preview__header">
      <div><img src="/brand/adcraft-icon.webp" alt="AdCraft" /><span>对话设计预览</span></div>
      <nav aria-label="预览状态">
        {([['choice', '选择方向'], ['working', '生成中'], ['confirmed', '已确认']] as const).map(([value, label]) => <button key={value} aria-pressed={scene === value} onClick={() => setScene(value, true)}>{label}</button>)}
      </nav>
      <LanguageSwitcher />
    </header>
    <main className="conversation-preview__workspace">
      <BrandDecisionPanel decisions={decisions} refreshing={false} onRefresh={notify} />
      <section className="conversation-preview__canvas" aria-label="画布预览">
        <p>日常 · 随行杯 <span>30 秒品牌广告</span></p>
        <div className="conversation-preview__note"><span>创意方向</span><h1>{scene === "choice" ? "一个属于自己的片刻。" : selectedTitle}</h1><p>从真实生活出发，让产品成为故事的一部分。</p><div>品牌记忆 <i /> 广告目标 <i /> 创意方向</div></div>
        <small>预览中的选择仅保留在此页面</small>
      </section>
      <AgentCanvasChatPanel key={previewEpoch} workflow={workflow} chatRevision={revision} chatEvents={[]} onFocusNode={() => {}} brandDecisions={decisions} />
    </main>
  </div>;
}
createRoot(document.getElementById("root")!).render(<LocaleProvider initialLocale="zh-CN"><Preview /></LocaleProvider>);
