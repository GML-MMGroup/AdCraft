import { useState } from "react";
import { createRoot } from "react-dom/client";
import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { normalizeBrandDecisionPanelV1 } from "../../src/features/agent-canvas/brand/brandDecisionNormalizers.ts";
import type { BrandSkillSelectionRequest } from "../../src/features/agent-canvas/brand/brandDecisions.ts";
import { BrandSkillPicker } from "../../src/features/agent-canvas/brand/BrandSkillPicker.tsx";
import { BrandDecisionPanel } from "../../src/features/agent-canvas/brand/BrandDecisionPanel.tsx";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

const methods = ["视觉隐喻", "私人仪式", "身份转变", "反直觉纠偏", "误导反转", "情感微瞬间", "收藏玩具世界"].map((title, index) => ({
  skill_id: `method-${index}`, version: "1.0.0", skill_kind: "creative_method" as const, title, summary: `创意方法示例 ${index + 1}`,
}));
const styles = ["电影写实", "诗意叙事", "商业质感", "微缩世界"].map((title, index) => ({
  skill_id: `style-${index}`, version: "1.0.0", title, summary: `视听风格示例 ${index + 1}`, category: "film",
  tags: [], supported_use_cases: [], preview: null, display_order: index,
}));
let panel = normalizeBrandDecisionPanelV1({
  project_id: "mock-project", workflow_id: "mock-workflow", mode: "brand", brand_name: "示例品牌",
  journey: { stage: "skill-stack", stage_revision: 5, stage_status: "waiting_user" },
  open_card: { card_id: "card-5", stage: "skill-stack", stage_revision: 5, question: "请选择创意方法与视听风格", options: [] },
  skill_stack: { entries: [
    { ...methods[0], selected: true, reason: "把产品价值变成观众可感知的画面。" },
    ...styles.slice(0, 3).map((style, index) => ({ ...style, skill_kind: "audiovisual_style", selected: index === 0, reason: "适合当前品牌和创意假设。" })),
  ] },
});
const probe = { writes: [] as BrandSkillSelectionRequest[], nextQuestions: 0, activations: 0 };
Object.assign(window, { brandSkillProbe: probe });
Object.assign(agentCanvasApi, {
brandCreativeMethodSkills: async () => ({ items: methods }),
brandDecisions: async () => panel,
listVideoSkills: async ({ cursor } = {}) => ({
  catalog_version: "1", categories: [{ category_id: "film", title: "影片风格", display_order: 0 }],
  items: cursor ? styles.slice(2) : styles.slice(0, 2), next_cursor: cursor ? null : "page-2",
}),
createAgentCanvasVideoSkillRun: async () => { probe.activations += 1; throw new Error("Unexpected activation"); },
brandSelectSkills: async (_id, request) => {
  probe.writes.push(request);
  if (request.expected_stage_revision !== panel.journey.stage_revision) throw new Error("Stale revision");
  const revision = panel.journey.stage_revision + 1;
  panel = { ...panel, journey: { ...panel.journey, stage_revision: revision, stage: request.confirm ? "treatment" : "skill-stack" },
    open_card: request.confirm ? null : { ...panel.open_card!, card_id: `card-${revision}`, stage_revision: revision },
    skill_stack: { entries: [
      ...methods.filter((method) => request.creative_methods.some((entry) => entry.skill_id === method.skill_id)).map((method) => ({ ...method, selected: true, reason: null })),
      ...styles.map((style) => ({ ...style, skill_kind: "audiovisual_style" as const, selected: style.skill_id === request.audiovisual_style.skill_id, reason: null })),
    ] },
  };
  return panel;
},
brandNextQuestion: async () => { probe.nextQuestions += 1; return null; },
} satisfies Partial<typeof agentCanvasApi>);

function Harness() {
  const [decisions, setDecisions] = useState(panel);
  const [open, setOpen] = useState(false);
  return <main style={{ width: "min(360px, 100%)", minHeight: "100vh" }}>
    <BrandDecisionPanel decisions={decisions} refreshing={false} onRefresh={() => {}} onChooseSkills={() => setOpen(true)} />
    <p data-testid="stage">{decisions.journey.stage}</p>
    {open ? <BrandSkillPicker decisions={decisions} responseLocale="zh-CN" onClose={() => setOpen(false)} onUpdated={setDecisions} onConversationRefresh={() => {}} /> : null}
  </main>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
