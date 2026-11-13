import { useId, useState, type KeyboardEvent } from "react";
import type { VideoSkillCatalogResponseV2, VideoSkillPreviewV2 } from "../../../types-v2.ts";
import { SkillCardContent } from "../chat/SkillCardContent.tsx";
import { skillBilingualTitles, skillCategoryTitle, skillDisplaySummary } from "../skills/skillDisplayCopy.ts";
import type { BrandCreativeMethod, BrandDecisionPanelV1, BrandSkillIdentity } from "./brandDecisions.ts";
import { creativeMethodPreview } from "./brandSkillPreviews.ts";

export type BrandStyleSelection = { skill_id: string; version: string | null; title: string };
type GalleryTab = "styles" | "methods" | "selected";
type GallerySkill = {
  skill_id: string;
  version: string | null;
  title: string;
  summary: string;
  kind: "style" | "method";
  category?: string;
  preview: VideoSkillPreviewV2 | null;
  available: boolean;
};

export function BrandSkillGallery({ catalog, styleCatalog, panel, methods, style, disabled, locale, onToggleMethod, onSelectStyle }: {
  catalog: readonly BrandCreativeMethod[];
  styleCatalog: VideoSkillCatalogResponseV2;
  panel: BrandDecisionPanelV1;
  methods: readonly BrandSkillIdentity[];
  style: BrandStyleSelection | null;
  disabled: boolean;
  locale: string;
  onToggleMethod: (method: BrandSkillIdentity) => void;
  onSelectStyle: (style: BrandStyleSelection | null) => void;
}) {
  const zh = locale.startsWith("zh");
  const id = useId();
  const [tab, setTab] = useState<GalleryTab>("styles");
  const [category, setCategory] = useState<string | null>(null);
  const selectedCount = methods.length + (style ? 1 : 0);
  const tabs = [
    { key: "styles" as const, label: zh ? "视听风格 Skill" : "Audiovisual Skills" },
    { key: "methods" as const, label: zh ? "创意风格 Skill" : "Creative Skills" },
    { key: "selected" as const, label: zh ? "已选 Skill" : "Selected Skills", count: selectedCount },
  ];
  const styleCards: GallerySkill[] = styleCatalog.items.map(skill => ({ ...skill, kind: "style", available: true }));
  const methodCards: GallerySkill[] = catalog.map<GallerySkill>(skill => ({
    ...skill, kind: "method", available: true, preview: creativeMethodPreview(skill.skill_id, styleCatalog.items),
  })).sort((a, b) => Number(Boolean(b.preview?.media_url)) - Number(Boolean(a.preview?.media_url)));
  // Keep stale selections visible so the user can remove or replace them.
  for (const method of methods) {
    if (methodCards.some(item => item.skill_id === method.skill_id && item.version === method.version)) continue;
    const entry = panel.skill_stack?.entries.find(item => item.skill_kind === "creative_method" && item.skill_id === method.skill_id);
    methodCards.push({ ...method, title: entry?.title ?? method.skill_id, summary: "", kind: "method", preview: null, available: false });
  }
  if (style && !styleCards.some(item => item.skill_id === style.skill_id && item.version === style.version)) {
    styleCards.push({ ...style, summary: "", kind: "style", preview: null, available: false });
  }
  const isSelected = (skill: GallerySkill) => skill.kind === "style"
    ? style?.skill_id === skill.skill_id && style.version === skill.version
    : methods.some(method => method.skill_id === skill.skill_id && method.version === skill.version);
  const visibleStyles = styleCards.filter(skill => tab === "selected" ? isSelected(skill) : !category || skill.category === category);
  const visibleMethods = methodCards.filter(skill => tab !== "selected" || isSelected(skill));

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const nextIndex = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
        : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    setTab(tabs[nextIndex].key);
    document.getElementById(`${id}-${tabs[nextIndex].key}`)?.focus();
  }
  function card(skill: GallerySkill) {
    const selected = isSelected(skill);
    const { chinese: title, english } = skillBilingualTitles(skill);
    const secondaryTitle = title !== english ? english : undefined;
    const reason = panel.skill_stack?.entries.find(entry => entry.skill_kind === (skill.kind === "style" ? "audiovisual_style" : "creative_method")
      && entry.skill_id === skill.skill_id && entry.version === skill.version)?.reason;
    const unavailable = !skill.available;
    const blocked = disabled || (!selected && (unavailable || (skill.kind === "method" && methods.length >= 7)));
    return <label key={`${skill.kind}:${skill.skill_id}@${skill.version}`}
      className={`agent-chat__style-option brand-skill-gallery__card${selected ? " is-selected" : ""}${blocked ? " is-disabled" : ""}`}
      title={[skillDisplaySummary(skill, locale), reason, unavailable ? (zh ? "此版本已不可用，请重新选择" : "This version is unavailable. Choose another Skill.") : null].filter(Boolean).join("\n")}
      data-skill-id={skill.skill_id}>
      <input type={skill.kind === "style" && tab !== "selected" ? "radio" : "checkbox"}
        name={skill.kind === "style" ? `${id}-style` : undefined} aria-label={secondaryTitle ? `${title} / ${secondaryTitle}` : title}
        checked={selected} disabled={blocked} onChange={() => {
          if (skill.kind === "style") onSelectStyle(selected && tab === "selected" ? null : skill);
          else if (skill.version) onToggleMethod({ skill_id: skill.skill_id, version: skill.version });
        }} />
      <SkillCardContent title={title} secondaryTitle={secondaryTitle} preview={skill.preview} selected={selected} chinese={zh} skeleton />
      {unavailable ? <span className="brand-skill-gallery__unavailable">{zh ? "需重新选择" : "Unavailable"}</span> : null}
    </label>;
  }

  return <>
    <div className="brand-skill-gallery__tabs" role="tablist" aria-label={zh ? "技能板块" : "Skill sections"}>
      {tabs.map((item, index) => <button key={item.key} id={`${id}-${item.key}`} type="button" role="tab"
        aria-selected={tab === item.key} aria-controls={`${id}-panel`} tabIndex={tab === item.key ? 0 : -1}
        onClick={() => setTab(item.key)} onKeyDown={event => onTabKey(event, index)}>
        {item.label}{item.count !== undefined ? <span>{item.count}</span> : null}
      </button>)}
    </div>
    <section id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} className="brand-skill-gallery__panel">
      {tab === "styles" ? <div className="agent-chat__style-categories brand-skill-gallery__categories" aria-label={zh ? "风格分类" : "Style categories"}>
        <button type="button" aria-pressed={category === null} onClick={() => setCategory(null)}>{zh ? "全部" : "All"}</button>
        {styleCatalog.categories.map(item => <button key={item.category_id} type="button" aria-pressed={category === item.category_id}
          onClick={() => setCategory(item.category_id)}>{skillCategoryTitle(item, locale)}</button>)}
      </div> : null}
      <div className="brand-skill-gallery__scroll" key={tab}>
        {tab === "selected" ? <>
          {visibleStyles.length ? <section className="brand-skill-gallery__group"><h3>{zh ? "视听风格" : "Audiovisual style"}<span>{visibleStyles.length}</span></h3><div className="brand-skill-gallery__grid">{visibleStyles.map(card)}</div></section> : null}
          {visibleMethods.length ? <section className="brand-skill-gallery__group"><h3>{zh ? "创意风格" : "Creative Skills"}<span>{visibleMethods.length}</span></h3><div className="brand-skill-gallery__grid">{visibleMethods.map(card)}</div></section> : null}
        </> : <div className="brand-skill-gallery__grid">{(tab === "styles" ? visibleStyles : visibleMethods).map(card)}</div>}
        {(tab === "styles" ? !visibleStyles.length : tab === "methods" ? !visibleMethods.length : !visibleStyles.length && !visibleMethods.length) ? (
          <div className="brand-skill-gallery__empty">
            <p>{tab === "selected" ? (zh ? "还没有选择 Skill" : "No Skills selected yet") : (zh ? "暂无可用 Skill" : "No Skills available")}</p>
            {tab === "selected" ? <button type="button" onClick={() => setTab("styles")}>{zh ? "浏览视听风格" : "Browse audiovisual Skills"}</button> : null}
          </div>
        ) : null}
      </div>
    </section>
  </>;
}
