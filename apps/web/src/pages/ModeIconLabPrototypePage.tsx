// THROWAWAY PROTOTYPE: a focused study for mode semantics and icon motion.
import { useMemo, useState } from "react";
import "./mode-icon-lab-prototype.css";

type IconFamily = "creation" | "brand";
type Tone = "neutral" | "paper" | "signal";
type PreviewState = "idle" | "hover" | "selected";

interface IconStudy {
  id: string;
  family: IconFamily;
  name: string;
  label: string;
  description: string;
  motion: string;
}

const studies: IconStudy[] = [
  {
    id: "auteur",
    family: "creation",
    name: "Auteur",
    label: "个人视角",
    description: "一条从空白取景框里长出来的想法轨迹。",
    motion: "轨迹被画出，火花轻轻亮起。",
  },
  {
    id: "storyboard",
    family: "creation",
    name: "Storyboard",
    label: "连续创作",
    description: "三个未完成的画格，表达从第一帧开始搭建故事。",
    motion: "画格依次错位，像翻过一张分镜。",
  },
  {
    id: "gesture",
    family: "creation",
    name: "Gesture",
    label: "灵感动作",
    description: "一个核心灵感被一笔带过，保留手工创作的速度感。",
    motion: "轨道追随核心点，停下时回到原位。",
  },
  {
    id: "system",
    family: "brand",
    name: "System",
    label: "品牌系统",
    description: "网格、轴线和注册点共同约束一个可复用的品牌标记。",
    motion: "辅助线收拢，中心标记锁定。",
  },
  {
    id: "signature",
    family: "brand",
    name: "Signature",
    label: "品牌签名",
    description: "一个可识别的签名落在基线和安全区之间。",
    motion: "基线从左向右描出，签名随后落位。",
  },
  {
    id: "campaign",
    family: "brand",
    name: "Campaign",
    label: "品牌传播",
    description: "多个内容载体围绕同一个核心身份组织成一组。",
    motion: "载体错峰展开，最后回到统一编排。",
  },
];

function AuteurIcon() {
  return (
    <svg viewBox="0 0 128 128" aria-hidden="true">
      <path className="icon-draw-frame" d="M22 40V22h18M88 22h18v18M106 88v18H88M40 106H22V88" />
      <path className="icon-draw-trail" d="M30 84c13 4 22 0 29-9 7-8 10-18 16-27 4-7 11-11 21-11" />
      <path className="icon-draw-spark" d="m76 31 4 11 11 4-11 4-4 11-4-11-11-4 11-4 4-11Z" />
      <circle className="icon-draw-core" cx="59" cy="77" r="5" />
      <path className="icon-draw-ray" d="M33 65h10M84 77h11M61 93v9" />
    </svg>
  );
}

function StoryboardIcon() {
  return (
    <svg viewBox="0 0 128 128" aria-hidden="true">
      <rect className="icon-frame-stack icon-frame-stack--one" x="20" y="28" width="66" height="48" rx="3" />
      <rect className="icon-frame-stack icon-frame-stack--two" x="30" y="40" width="66" height="48" rx="3" />
      <rect className="icon-frame-stack icon-frame-stack--three" x="40" y="52" width="66" height="48" rx="3" />
      <path className="icon-frame-content" d="M50 88h14l7-12 9 7 9-12 9 17" />
      <path className="icon-frame-cursor" d="m26 21 12 21 5-9 10-1-27-11Z" />
    </svg>
  );
}

function GestureIcon() {
  return (
    <svg viewBox="0 0 128 128" aria-hidden="true">
      <path className="icon-gesture-orbit" d="M30 71c0-22 17-39 39-39 19 0 31 11 31 26 0 18-17 36-40 36-17 0-30-8-30-23Z" />
      <circle className="icon-gesture-core" cx="68" cy="58" r="10" />
      <path className="icon-gesture-ray" d="M68 36v-9M68 89v9M46 58h-9M90 58h9" />
      <path className="icon-gesture-tail" d="M31 72c-7 5-10 11-7 17 3 5 10 7 17 4" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg viewBox="0 0 128 128" aria-hidden="true">
      <rect className="icon-system-grid" x="22" y="22" width="84" height="84" rx="12" />
      <path className="icon-system-guides" d="M22 50h84M22 78h84M50 22v84M78 22v84" />
      <path className="icon-system-mark" d="m64 39 18 13v24L64 89 46 76V52l18-13Z" />
      <path className="icon-system-axis" d="M64 47v35M52 65h24" />
      <circle className="icon-system-node" cx="30" cy="30" r="3" />
      <circle className="icon-system-node" cx="98" cy="30" r="3" />
      <circle className="icon-system-node" cx="30" cy="98" r="3" />
      <circle className="icon-system-node" cx="98" cy="98" r="3" />
    </svg>
  );
}

function SignatureIcon() {
  return (
    <svg viewBox="0 0 128 128" aria-hidden="true">
      <path className="icon-signature-safe" d="M29 35V25h10M89 25h10v10M99 89v10H89M39 99H29V89" />
      <path className="icon-signature-baseline" d="M24 88h80" />
      <path className="icon-signature-mark" d="M39 76c7-22 13-31 20-31 5 0 4 11-4 21-7 9-14 13-20 10 7 7 20 5 31-7 8-9 13-16 19-16 5 0 5 7-2 14-6 6-13 9-21 8" />
      <circle className="icon-signature-dot" cx="97" cy="87" r="3" />
    </svg>
  );
}

function CampaignIcon() {
  return (
    <svg viewBox="0 0 128 128" aria-hidden="true">
      <rect className="icon-campaign-card icon-campaign-card--back" x="28" y="24" width="64" height="43" rx="5" />
      <rect className="icon-campaign-card icon-campaign-card--mid" x="20" y="38" width="64" height="43" rx="5" />
      <rect className="icon-campaign-card icon-campaign-card--front" x="36" y="52" width="64" height="43" rx="5" />
      <path className="icon-campaign-line" d="M49 73h30M49 82h18" />
      <circle className="icon-campaign-dot" cx="87" cy="60" r="4" />
    </svg>
  );
}

function StudyIcon({ id }: { id: string }) {
  if (id === "auteur") return <AuteurIcon />;
  if (id === "storyboard") return <StoryboardIcon />;
  if (id === "gesture") return <GestureIcon />;
  if (id === "system") return <SystemIcon />;
  if (id === "signature") return <SignatureIcon />;
  return <CampaignIcon />;
}

function IconStudyCard({ study, previewState, selected, onSelect }: { study: IconStudy; previewState: PreviewState; selected: boolean; onSelect: () => void }) {
  return (
    <button
      className={`icon-study-card icon-study-card--${study.id}${selected ? " is-selected" : ""}`}
      type="button"
      data-preview-state={previewState}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="icon-study-card__topline">
        <span>{study.family === "creation" ? "CREATION" : "BRAND"}</span>
        <span>{study.name}</span>
      </span>
      <span className="icon-study-card__icon"><StudyIcon id={study.id} /></span>
      <span className="icon-study-card__copy">
        <strong>{study.label}</strong>
        <span>{study.description}</span>
      </span>
      <span className="icon-study-card__motion"><i aria-hidden="true" /> {study.motion}</span>
    </button>
  );
}

export function ModeIconLabPrototypePage() {
  const [tone, setTone] = useState<Tone>(() => {
    const requested = new URLSearchParams(window.location.search).get("tone");
    return requested === "paper" || requested === "signal" ? requested : "neutral";
  });
  const [previewState, setPreviewState] = useState<PreviewState>("idle");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const groupedStudies = useMemo(() => ({
    creation: studies.filter((study) => study.family === "creation"),
    brand: studies.filter((study) => study.family === "brand"),
  }), []);

  function changeTone(nextTone: Tone) {
    setTone(nextTone);
    window.history.replaceState(null, "", `${window.location.pathname}?tone=${nextTone}`);
    setSelectedId(null);
  }

  return (
    <main className={`mode-icon-lab mode-icon-lab--${tone}`}>
      <header className="icon-lab-header">
        <span className="icon-lab-header__brand">ADCRAFT <span>/ MODE ICON STUDY</span></span>
        <span className="icon-lab-header__status"><i aria-hidden="true" /> SEMANTIC EXPLORATION</span>
      </header>

      <section className="icon-lab-intro">
        <span className="icon-lab-kicker">Two modes / six marks / one visual language</span>
        <h1>图标研究场</h1>
        <p>先确认它表达什么，再决定它如何运动。点击卡片查看选中状态，也可以切换底部预览模式。</p>
      </section>

      <section className="icon-lab-family" aria-labelledby="creation-study-heading">
        <div className="icon-lab-family__heading">
          <span className="icon-lab-family__number">01</span>
          <div><h2 id="creation-study-heading">个人创作</h2><p>One point of view · from blank frame to first idea</p></div>
        </div>
        <div className="icon-study-grid">
          {groupedStudies.creation.map((study) => <IconStudyCard key={study.id} study={study} previewState={previewState} selected={selectedId === study.id} onSelect={() => setSelectedId(study.id)} />)}
        </div>
      </section>

      <section className="icon-lab-family" aria-labelledby="brand-study-heading">
        <div className="icon-lab-family__heading">
          <span className="icon-lab-family__number">02</span>
          <div><h2 id="brand-study-heading">品牌专业</h2><p>Identity system · from mark to campaign language</p></div>
        </div>
        <div className="icon-study-grid">
          {groupedStudies.brand.map((study) => <IconStudyCard key={study.id} study={study} previewState={previewState} selected={selectedId === study.id} onSelect={() => setSelectedId(study.id)} />)}
        </div>
      </section>

      <aside className="icon-lab-dock" aria-label="Icon study controls">
        <div className="icon-lab-dock__group">
          <span className="icon-lab-dock__label">Preview state</span>
          {(["idle", "hover", "selected"] as PreviewState[]).map((state) => <button className={previewState === state ? "is-active" : ""} type="button" key={state} onClick={() => setPreviewState(state)}>{state}</button>)}
        </div>
        <div className="icon-lab-dock__group">
          <span className="icon-lab-dock__label">Tone</span>
          {(["neutral", "paper", "signal"] as Tone[]).map((nextTone) => <button className={tone === nextTone ? "is-active" : ""} type="button" key={nextTone} onClick={() => changeTone(nextTone)}>{nextTone}</button>)}
        </div>
      </aside>
    </main>
  );
}
