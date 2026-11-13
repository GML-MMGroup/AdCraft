import { useUiLocale } from "../../../i18n/locale.tsx";
import { skillDisplayTitle, skillDisplaySummary, skillCategoryTitle } from "../skills/skillDisplayCopy.ts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { CloseIcon } from "../../../icons.tsx";
import type {
  ActiveStyleSkillSummaryV2,
  VideoSkillCatalogResponseV2,
  VideoSkillPublicDetailV2,
} from "../../../types-v2.ts";
import { SkillCardContent } from "./SkillCardContent.tsx";
import { loadVideoSkillCatalog } from "../skills/loadVideoSkillCatalog.ts";

type StyleSelectorProps = {
  workflowId: string;
  activeStyle: ActiveStyleSkillSummaryV2 | null;
  onWorkflowRefresh: () => Promise<void> | void;
  onSkillSelected?: (title: string | null) => void;
  draftSelection?: {
    selected: { skill_id: string; version: string } | null;
    onSelect: (skill: VideoSkillPublicDetailV2) => void;
  };
  triggerLabel?: string;
  responseLocale?: string;
};

function StyleLoadingState({ chinese = false }: { chinese?: boolean }) {
  return (
    <div className="agent-chat__style-loading" role="status" aria-label={chinese ? "正在加载风格预览" : "Loading Style previews"}>
      <span className="agent-chat__style-loading-label" aria-hidden="true">{chinese ? "正在加载风格…" : "Loading Styles..."}</span>
      {Array.from({ length: 4 }, (_, index) => (
        <div
          key={index}
          className="agent-chat__style-loading-card"
          data-testid="style-loading-card"
          aria-hidden="true"
        >
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

type StyleCardProps = {
  skill: VideoSkillPublicDetailV2;
  selected: boolean;
  activating: boolean;
  disabled: boolean;
  onSelect: () => void;
  chinese?: boolean;
};

function StyleCard({ skill, selected, activating, disabled, onSelect, chinese = false }: StyleCardProps) {
  return (
    <button
      type="button"
      className={`agent-chat__style-option${selected ? " is-selected" : ""}`}
      aria-pressed={selected}
      data-preview={skill.preview?.kind ?? "placeholder"}
      disabled={disabled}
      onClick={onSelect}
    >
      <SkillCardContent title={skillDisplayTitle(skill, chinese ? "zh-CN" : "en-US")}
        summary={skillDisplaySummary(skill, chinese ? "zh-CN" : "en-US")}
        preview={skill.preview} selected={selected} activating={activating} chinese={chinese} />
    </button>
  );
}

export function AgentCanvasStyleSelector({
  workflowId,
  activeStyle,
  onWorkflowRefresh,
  onSkillSelected,
  draftSelection,
  triggerLabel,
  responseLocale = "en",
}: StyleSelectorProps) {
  const locale = useUiLocale(responseLocale);
  const chinese = locale.startsWith("zh");
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<VideoSkillCatalogResponseV2 | null>(null);
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activatingSkillId, setActivatingSkillId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLElement>(null);
  const lastActiveStyleRunIdRef = useRef<string | null>(
    activeStyle?.skill_run_id ?? null,
  );

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextCatalog = await loadVideoSkillCatalog();
      setCatalog(nextCatalog);
      setActiveCategoryId((current) => {
        if (current && nextCatalog.categories.some((category) => category.category_id === current)) {
          return current;
        }
        if (activeStyle && nextCatalog.categories.some(
          (category) => category.category_id === activeStyle.category,
        )) {
          return activeStyle.category;
        }
        return nextCatalog.categories[0]?.category_id ?? null;
      });
    } catch (catalogError) {
      setError(chinese ? "视听风格加载失败，请重试。" : catalogError instanceof Error ? catalogError.message : "Styles could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [activeStyle, chinese]);

  useEffect(() => {
    setOpen(false);
    setCatalog(null);
    setError(null);
  }, [workflowId]);

  useEffect(() => {
    const nextRunId = activeStyle?.skill_run_id ?? null;
    if (nextRunId === lastActiveStyleRunIdRef.current) return;
    lastActiveStyleRunIdRef.current = nextRunId;
    if (
      open && activeStyle && catalog?.categories.some(
        (category) => category.category_id === activeStyle.category,
      )
    ) setActiveCategoryId(activeStyle.category);
  }, [activeStyle, catalog?.categories, open]);

  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    const returnFocusTarget = triggerRef.current;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !activatingSkillId) setOpen(false);
      if (event.key !== "Tab") return;
      const controls = menuRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]');
      const first = controls?.[0];
      const last = controls?.[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
      returnFocusTarget?.focus();
    };
  }, [activatingSkillId, open]);

  const categories = catalog?.categories ?? [];
  const visibleSkills = useMemo(() => (catalog?.items ?? []).filter((skill) => (
    skill.category === activeCategoryId
  )), [activeCategoryId, catalog?.items]);

  async function togglePicker() {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen && !catalog && !loading) await loadCatalog();
  }

  async function activateStyle(skill: VideoSkillPublicDetailV2) {
    if (draftSelection) {
      draftSelection.onSelect(skill);
      setOpen(false);
      return;
    }
    if (activatingSkillId) return;
    onSkillSelected?.(skillDisplayTitle(skill, locale));
    setActivatingSkillId(skill.skill_id);
    setError(null);
    try {
      const activated = await agentCanvasApi.createAgentCanvasVideoSkillRun(
        workflowId,
        {
          skill_id: skill.skill_id,
          skill_version: skill.version,
          source_skill_run_id: activeStyle?.skill_run_id ?? null,
        },
        createOperationKey("style"),
      );
      if (!activated.active_creative_direction_snapshot_id) {
        throw new Error("The selected Style is not ready yet. Your previous Style remains active.");
      }
      await onWorkflowRefresh();
      setOpen(false);
    } catch (activationError) {
      onSkillSelected?.(activeStyle ? skillDisplayTitle(activeStyle, locale) : null);
      if (isV2ApiError(activationError)) {
        if (activationError.code === "style_skill_activation_conflict") {
          try {
            await onWorkflowRefresh();
          } catch {
            // Keep the authoritative conflict visible even when its refresh also fails.
          }
        } else if (activationError.code === "video_skill_not_found") {
          await loadCatalog();
        }
      }
      setError(
        activationError instanceof Error
          ? activationError.message
          : "The selected Style could not be activated.",
      );
    } finally {
      setActivatingSkillId(null);
    }
  }

  return (
    <div className="agent-chat__style-selector">
      <button
        type="button"
        ref={triggerRef}
        className={`agent-chat__style-trigger${open ? " is-active" : ""}`}
        aria-label={triggerLabel ?? (chinese ? "技能" : "Skill")}
        title={triggerLabel ?? (chinese ? "技能" : "Skill")}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => void togglePicker()}
      >
        <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" />
        {triggerLabel ? <span>{triggerLabel}</span> : null}
      </button>

      {open && typeof document !== "undefined" ? createPortal(
        <div className="agent-chat__style-overlay">
          <button
            type="button"
            className="agent-chat__style-backdrop"
            aria-label={chinese ? "取消选择视听风格" : "Dismiss Choose video Style"}
            tabIndex={-1}
            onClick={() => {
              if (!activatingSkillId) setOpen(false);
            }}
          />
          <section
            ref={menuRef}
            className="agent-chat__style-menu"
            role="dialog"
            aria-modal="true"
            aria-label={chinese ? "选择视听风格" : "Choose video Style"}
          >
          <header className="agent-chat__style-menu-header">
            <div>
              <strong>{chinese ? "选择视听风格" : "Choose visual language"}</strong>
            </div>
            <button
              type="button"
              aria-label={chinese ? "关闭视听风格选择" : "Close Style picker"}
              autoFocus
              disabled={Boolean(activatingSkillId)}
              onClick={() => setOpen(false)}
            >
              <CloseIcon />
            </button>
          </header>

          {loading ? <StyleLoadingState chinese={chinese} /> : null}
          {error ? (
            <div className="agent-chat__style-error" role="alert">
              <span>{error}</span>
              {!catalog ? (
                <button type="button" onClick={() => void loadCatalog()}>{chinese ? "重试" : "Retry"}</button>
              ) : null}
            </div>
          ) : null}

          {catalog ? (
            <>
              <div className="agent-chat__style-categories" role="tablist" aria-label={chinese ? "风格分类" : "Style categories"}>
                {categories.map((category) => (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={category.category_id === activeCategoryId}
                    key={category.category_id}
                    onClick={() => setActiveCategoryId(category.category_id)}
                  >
                    {skillCategoryTitle(category, locale)}
                  </button>
                ))}
              </div>
              <div className="agent-chat__style-list">
                {visibleSkills.map((skill) => {
                  const selected = draftSelection
                    ? skill.skill_id === draftSelection.selected?.skill_id && skill.version === draftSelection.selected.version
                    : skill.skill_id === activeStyle?.skill_id && skill.version === activeStyle.skill_version;
                  const activating = activatingSkillId === skill.skill_id;
                  return (
                    <StyleCard
                      chinese={chinese}
                      key={`${skill.skill_id}@${skill.version}`}
                      skill={skill}
                      selected={selected}
                      activating={activating}
                      disabled={Boolean(activatingSkillId)}
                      onSelect={() => void activateStyle(skill)}
                    />
                  );
                })}
                {!visibleSkills.length ? (
                  <p className="agent-chat__style-empty">{chinese ? "此分类暂无可用风格。" : "No Styles are available in this category."}</p>
                ) : null}
              </div>
            </>
          ) : null}
          </section>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
