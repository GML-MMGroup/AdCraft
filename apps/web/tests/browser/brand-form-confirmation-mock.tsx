import { useState } from "react";
import { createRoot } from "react-dom/client";
import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { LocaleProvider } from "../../src/i18n/locale.tsx";
import { AgentCanvasChatPanel } from "../../src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx";
import { BrandDecisionPanel } from "../../src/features/agent-canvas/brand/BrandDecisionPanel.tsx";
import { normalizeBrandDecisionPanelV1 } from "../../src/features/agent-canvas/brand/brandDecisionNormalizers.ts";
import type { AgentCanvasWorkflowV2, GuidedInteractionV1, GuidedSessionStateV2 } from "../../src/types-v2.ts";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";
import "./brand-form-confirmation-preview.css";

// This preview runs the production chat panel with in-memory API responses.
const campaign = new URLSearchParams(location.search).get("stage") === "campaign";
const submitDelay = Number(new URLSearchParams(location.search).get("submitDelay") ?? 180);
const submitFails = new URLSearchParams(location.search).get("submitFails") === "true";
const stage: "campaign" | "brand-memory" = campaign ? "campaign" : "brand-memory";
const workflow: AgentCanvasWorkflowV2 = {
  workflow_id: "brand-confirmation-preview", project_id: "preview-project",
  workflow_schema_version: 2, canvas_model: "agent_canvas_v1", revision: 1,
  layout_revision: 1, nodes: [], bindings: [], assets: [], active_style_skill: null,
};
const fields = campaign ? [
  { slot: "campaign_goal", prompt: "本次广告希望达成什么目标？", choices: ["新品发布", "品牌认知", "促进购买"] },
  { slot: "campaign_platform", prompt: "广告主要在哪里投放？", choices: ["小红书", "抖音", "电商详情页"] },
  { slot: "campaign_duration", prompt: "广告时长是多少？", choices: ["15 秒", "30 秒", "60 秒"] },
] : [
  { slot: "brand_product_identity", prompt: "这支广告的主角是什么？", choices: ["轻量随行水杯", "保温杯", "玻璃水杯"] },
  { slot: "brand_audience", prompt: "品牌主要面向哪些人？", choices: ["都市通勤人群", "户外爱好者", "学生群体"] },
  { slot: "brand_tone", prompt: "希望呈现怎样的品牌气质？", choices: ["简约自然", "活力明快", "精致沉稳"] },
];
const form: GuidedInteractionV1 = {
  workflow_id: workflow.workflow_id, interaction_id: `preview-${stage}-form`, session_id: "preview-session",
  checkpoint_id: "preview-checkpoint", kind: "brand_form", status: "open", response_locale: "zh-CN",
  expected_session_revision: 1, revision: 1, title: campaign ? "本次广告需求" : "品牌基础信息",
  context: "请选择每项内容，确认后将保存在左侧面板。",
  content: {
    content_kind: "brand_form", form_id: `preview-${stage}`, stage, revision: 1,
    response_locale: "zh-CN", context_digest: "a".repeat(64),
    title: campaign ? "确认本次广告需求" : "确认品牌基础信息",
    instructions: "每项选择一个选项，也可以填写自定义内容。",
    rows: fields.map(field => ({
      question_id: field.slot, slot_id: field.slot, prompt: field.prompt, required: true,
      custom_option_id: "custom",
      options: [...field.choices.map((label, index) => ({ option_id: String(index), label, why: null })),
        { option_id: "custom", label: "自定义", why: null }],
    })),
  },
  allowed_actions: ["select", "custom"], submit_path: "/preview-only",
  created_at: "2026-11-09T02:00:00Z", updated_at: "2026-11-09T02:00:00Z",
};
let decisions = normalizeBrandDecisionPanelV1({
  workflow_id: workflow.workflow_id, project_id: workflow.project_id, mode: "brand", brand_name: "日常 · 随行杯",
  journey: { stage, stage_revision: 1, stage_status: "waiting_user" },
  slot_values: [], open_card: null,
});
let session: GuidedSessionStateV2 = {
  session_id: "preview-session", workflow_id: workflow.workflow_id, status: "active", response_locale: "zh-CN",
  goal: { requested_output: "video", delivery_scope: "generated_media", summary: "水杯创意广告", explicit_constraints: {} },
  creative_authority: null, current_checkpoint: null, narrative_direction: null, element_decisions: [],
  current_topic_id: null, topics: [], active_proposal_id: null, active_style_skill_run_id: null,
  completion: { authoring: "not_ready", delivery: "not_ready", editing_preparation: "not_ready",
    editing_node_id: null, matching_node_ids: [], matching_asset_ids: [], plan_document_id: null, plan_revision: null,
    preparation_receipt_id: null, manifest_revision: null, export_status: "not_started", export_id: null,
    final_completion_receipt_id: null, final_asset_id: null },
  journey: { policy_version: "fixed_ad_production_v2", stage: "intake", stage_status: "waiting_user", stage_revision: 1,
    decisions: [], active_occurrence_id: null, active_action: null, suspended_action: null, transition_evidence: [] },
  interaction: form, awaiting: null, revision: 1, updated_at: "2026-11-09T02:00:00Z",
};

Object.assign(agentCanvasApi, {
  agentCanvasExecutionSettings: async () => ({ etag: '"preview-settings"', value: {
    workflow_id: workflow.workflow_id, media_execution_mode: "manual", revision: 1,
    created_at: "2026-11-09T02:00:00Z", updated_at: "2026-11-09T02:00:00Z",
  } }),
  listAgentCanvasDocuments: async () => ({ workflow_id: workflow.workflow_id, items: [], next_cursor: null }),
  agentCanvasCreativeSession: async () => session,
  agentCanvasChatTimeline: async () => ({
    workflow_id: workflow.workflow_id, conversation_id: "preview-conversation", guidanceSession: session,
    guidanceAdvancePrecondition: null, continuations: [], current_session_actions: [], presentationItems: null,
    items: [{ item_type: "message", message_kind: "conversation", message_id: "preview-intro",
      conversation_id: "preview-conversation", speaker: "adcraft_video_agent",
      text: campaign ? "接下来，请确认这次广告的目标、投放渠道和时长。" : "我们先梳理产品与品牌方向。请在下方表单中选择符合这支广告的内容。",
      linked_node_ids: [], script_node_id: null, proposal_id: null, capability_id: null,
      sequence: 1, created_at: "2026-11-09T02:00:00Z" }], next_cursor: 1,
  }),
  brandDecisions: async () => decisions,
  brandNextQuestion: async () => null,
  submitAgentCanvasGuidedInteraction: async (_workflowId, _interactionId, request) => {
    if (request.submission_kind !== "brand_form") throw new Error("Expected brand form");
    await new Promise(resolve => window.setTimeout(resolve, submitDelay));
    if (submitFails) throw new Error("提交失败，请重试。");
    const values = request.answers.map(answer => {
      const field = fields.find(item => item.slot === answer.question_id)!;
      return { slot_id: field.slot, stage,
        value: answer.selected_option_id === "custom" ? answer.custom_text! : field.choices[Number(answer.selected_option_id)]!,
        kind: "fact" as const, provenance: "user_confirmed" as const, confirmed_at: new Date().toISOString() };
    });
    decisions = { ...decisions, slot_values: values,
      journey: { ...decisions.journey, stage: campaign ? "skill-stack-early" : "campaign", stage_revision: 2 },
      [campaign ? "campaign_brief" : "brand_profile"]: { values, inherited_values: [], unresolved_fields: [] } };
    session = { ...session, revision: 2, interaction: { ...form, status: "submitted" } };
    return { workflow_id: workflow.workflow_id, interaction_id: form.interaction_id, submission_id: "preview-submission",
      receipt_id: "preview-receipt", created_node_ids: [], created_binding_ids: [], document_revisions: {},
      continuation_id: null, automatic_run_command_ids: [], resulting_session_revision: 2, events_cursor: 1, replayed: false };
  },
} satisfies Partial<typeof agentCanvasApi>);

function Preview() {
  const [panel, setPanel] = useState(decisions);
  return <>
    <header className="confirmation-preview__header">
      <a href="/tests/browser/brand-form-confirmation-mock.html" className="confirmation-preview__identity">AdCraft <span>表单确认提示预览</span></a>
      <nav aria-label="预览阶段">
        <a href="?stage=brand-memory" aria-current={!campaign ? "page" : undefined}>品牌信息</a>
        <a href="?stage=campaign" aria-current={campaign ? "page" : undefined}>广告需求</a>
        <button type="button" onClick={() => location.reload()}>重新体验</button>
      </nav>
    </header>
    <main className="confirmation-preview__workspace">
      <BrandDecisionPanel decisions={panel} refreshing={false} onRefresh={() => setPanel(decisions)} />
      <div className="confirmation-preview__canvas"><p>水杯品牌广告<span>选择表单选项后，点击「确认整张表」查看提示效果。</span></p></div>
      <AgentCanvasChatPanel workflow={workflow} chatRevision={0} chatEvents={[]} onFocusNode={() => {}}
        brandMode brandContextReady brandStage={panel.journey.stage} brandDecisions={panel}
        onBrandDecisionsRefresh={async () => { setPanel(decisions); return decisions.journey.stage; }} />
    </main>
  </>;
}

createRoot(document.getElementById("root")!).render(<LocaleProvider initialLocale="zh-CN"><Preview /></LocaleProvider>);
