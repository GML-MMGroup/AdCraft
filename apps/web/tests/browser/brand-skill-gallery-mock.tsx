import { useState } from "react";
import { createRoot } from "react-dom/client";
import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { LocaleProvider } from "../../src/i18n/locale.tsx";
import { BrandSkillPicker } from "../../src/features/agent-canvas/brand/BrandSkillPicker.tsx";
import { normalizeBrandDecisionPanelV1 } from "../../src/features/agent-canvas/brand/brandDecisionNormalizers.ts";
import type { BrandSkillSelectionRequest } from "../../src/features/agent-canvas/brand/brandDecisions.ts";
import { loadVideoSkillCatalog } from "../../src/features/agent-canvas/skills/loadVideoSkillCatalog.ts";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/agent-canvas-page.css";

async function startPreview() {
  const [methods, styles] = await Promise.all([agentCanvasApi.brandCreativeMethodSkills(), loadVideoSkillCatalog()]);
  const initial = normalizeBrandDecisionPanelV1({
    project_id: "skill-gallery-preview", workflow_id: "skill-gallery-preview", mode: "brand", brand_name: "夏日品牌广告",
    journey: { stage: "skill-stack-early", stage_revision: 5, stage_status: "waiting_user" },
    open_card: { card_id: "preview-card-5", stage: "skill-stack-early", stage_revision: 5, question: "选择你的技能组合", options: [] },
    skill_stack: { entries: [
      ...methods.items.filter(item => ["summer-sensory-use-moment", "collision-montage"].includes(item.skill_id)).map(item => ({ ...item, selected: true, reason: null })),
      ...styles.items.filter(item => item.skill_id === "japanese-summer-sensory-film").map(item => ({ ...item, skill_kind: "audiovisual_style", selected: true, reason: null })),
    ] },
  });
  let saved = initial;
  // Preview-only writes stay in memory. The production component still uses its normal contract.
  Object.assign(agentCanvasApi, {
    brandSelectSkills: async (_workflowId: string, request: BrandSkillSelectionRequest) => {
      window.dispatchEvent(new CustomEvent("skill-gallery-preview-save", { detail: request }));
      saved = normalizeBrandDecisionPanelV1({
        ...saved,
        journey: { ...saved.journey, stage_revision: saved.journey.stage_revision + 1, stage: request.confirm ? "hypothesis" : "skill-stack-early" },
        open_card: request.confirm ? null : { ...saved.open_card, card_id: `preview-card-${saved.journey.stage_revision + 1}`, stage_revision: saved.journey.stage_revision + 1 },
        skill_stack: { entries: [
          ...request.creative_methods.map(identity => ({ ...methods.items.find(item => item.skill_id === identity.skill_id), ...identity, skill_kind: "creative_method", selected: true })),
          { ...styles.items.find(item => item.skill_id === request.audiovisual_style.skill_id), ...request.audiovisual_style, skill_kind: "audiovisual_style", selected: true },
        ] },
      });
      return saved;
    },
    brandNextQuestion: async () => null,
    brandDecisions: async () => saved,
  });
  function Preview() {
    const [open, setOpen] = useState(true);
    const [panel, setPanel] = useState(initial);
    const [reset, setReset] = useState(0);
    return <LocaleProvider initialLocale="zh-CN">
      <main style={{ minHeight: "100dvh", background: "#141414", color: "#eeeae4", padding: 32, fontFamily: '"Manrope", "PingFang SC", sans-serif' }}>
        <img src="/brand/adcraft-icon.webp" alt="AdCraft" width="60" height="60" />
        <h1 style={{ fontSize: 24, fontWeight: 500 }}>技能组合预览</h1>
        <p style={{ color: "#a3a3a3", fontSize: 14 }}>使用实际技能目录，保存操作仅用于预览。</p>
        <button onClick={() => setOpen(true)}>打开技能面板</button>{" "}
        <button onClick={() => { saved = initial; setPanel(initial); setReset(value => value + 1); setOpen(true); }}>重置预览</button>
        <BrandSkillPicker key={reset} open={open} decisions={panel} responseLocale="zh-CN" onClose={() => setOpen(false)} onUpdated={setPanel} onConversationRefresh={() => {}} />
      </main>
    </LocaleProvider>;
  }
  createRoot(document.getElementById("root")!).render(<Preview />);
}
startPreview().catch(() => {
  document.getElementById("root")!.textContent = "技能目录暂时无法加载，请确认后端已启动后刷新。";
});
