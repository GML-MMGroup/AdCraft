import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { CloseIcon, ConfirmIcon } from "../../../icons.tsx";
import type {
  ActiveStyleSkillSummaryV2,
  VideoSkillCatalogResponseV2,
  VideoSkillCategoryV2,
  VideoSkillPublicDetailV2,
} from "../../../types-v2.ts";

type StyleSelectorProps = {
  workflowId: string;
  activeStyle: ActiveStyleSkillSummaryV2 | null;
  onWorkflowRefresh: () => Promise<void> | void;
};

const STYLE_CATALOG_PAGE_SIZE = 100;
const STYLE_SEARCH_THRESHOLD = 8;

function compareDisplayOrder(
  left: { display_order: number; title: string },
  right: { display_order: number; title: string },
) {
  return left.display_order - right.display_order;
}

function matchesPublicMetadata(skill: VideoSkillPublicDetailV2, query: string) {
  if (!query) return true;
  return [
    skill.title,
    skill.summary,
    ...skill.tags,
    ...skill.supported_use_cases,
  ].some((value) => value.toLocaleLowerCase().includes(query));
}

function StylePreview({ skill }: { skill: VideoSkillPublicDetailV2 }) {
  if (skill.preview?.kind === "image" && skill.preview.media_url) {
    return <img src={skill.preview.media_url} alt="" loading="lazy" />;
  }
  if (skill.preview?.kind === "video" && skill.preview.media_url) {
    return <video src={skill.preview.media_url} muted playsInline preload="metadata" />;
  }
  return (
    <span className="agent-chat__style-preview-placeholder" data-preview="placeholder" aria-label="No preview available">
      <span className="agent-chat__style-preview-sprockets" aria-hidden="true">
        {Array.from({ length: 7 }, (_, index) => <i key={index} />)}
      </span>
      <span aria-hidden="true">No preview</span>
    </span>
  );
}

type StyleCardProps = {
  skill: VideoSkillPublicDetailV2;
  selected: boolean;
  activating: boolean;
  disabled: boolean;
  onSelect: () => void;
};

function StyleCard({ skill, selected, activating, disabled, onSelect }: StyleCardProps) {
  return (
    <button
      type="button"
      className={`agent-chat__style-option${selected ? " is-selected" : ""}`}
      aria-pressed={selected}
      data-preview={skill.preview?.kind ?? "placeholder"}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="agent-chat__style-preview">
        <StylePreview skill={skill} />
        {selected ? (
          <span className="agent-chat__style-selected-mark" aria-label="Selected">
            <ConfirmIcon />
          </span>
        ) : null}
        {activating ? (
          <span className="agent-chat__style-applying" role="status">Applying…</span>
        ) : null}
      </span>
      <span className="agent-chat__style-option-copy">
        <strong>{skill.title}</strong>
        <small>{skill.summary}</small>
      </span>
    </button>
  );
}

function mergeCatalogPages(pages: VideoSkillCatalogResponseV2[]): VideoSkillCatalogResponseV2 {
  const categories = new Map<string, VideoSkillCategoryV2>();
  const items = new Map<string, VideoSkillPublicDetailV2>();
  pages.forEach((page) => {
    page.categories.forEach((category) => categories.set(category.category_id, category));
    page.items.forEach((skill) => items.set(`${skill.skill_id}@${skill.version}`, skill));
  });
  return {
    catalog_version: pages.at(-1)?.catalog_version ?? "unknown",
    categories: [...categories.values()].sort(compareDisplayOrder),
    items: [...items.values()].sort(compareDisplayOrder),
    next_cursor: null,
  };
}

export function AgentCanvasStyleSelector({
  workflowId,
  activeStyle,
  onWorkflowRefresh,
}: StyleSelectorProps) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<VideoSkillCatalogResponseV2 | null>(null);
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [activatingSkillId, setActivatingSkillId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastActiveStyleRunIdRef = useRef<string | null>(
    activeStyle?.skill_run_id ?? null,
  );

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const pages: VideoSkillCatalogResponseV2[] = [];
      const seenCursors = new Set<string>();
      let cursor: string | null = null;
      do {
        const page = await agentCanvasApi.listVideoSkills({
          limit: STYLE_CATALOG_PAGE_SIZE,
          ...(cursor ? { cursor } : {}),
        });
        pages.push(page);
        cursor = page.next_cursor;
        if (cursor && seenCursors.has(cursor)) {
          throw new Error("The Style catalog returned a repeated page cursor.");
        }
        if (cursor) seenCursors.add(cursor);
      } while (cursor);

      const nextCatalog = mergeCatalogPages(pages);
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
      setError(catalogError instanceof Error ? catalogError.message : "Styles could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [activeStyle]);

  useEffect(() => {
    setOpen(false);
    setCatalog(null);
    setSearchQuery("");
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
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !activatingSkillId) setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [activatingSkillId, open]);

  const categories = catalog?.categories ?? [];
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const visibleSkills = useMemo(() => (catalog?.items ?? []).filter((skill) => (
    skill.category === activeCategoryId && matchesPublicMetadata(skill, normalizedQuery)
  )), [activeCategoryId, catalog?.items, normalizedQuery]);

  async function togglePicker() {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen && !catalog && !loading) await loadCatalog();
  }

  async function activateStyle(skill: VideoSkillPublicDetailV2) {
    if (activatingSkillId) return;
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
        className={`agent-chat__style-trigger${open ? " is-active" : ""}`}
        aria-label="Skill"
        title="Skill"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => void togglePicker()}
      >
        <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" />
      </button>

      {open ? (
        <section
          className="agent-chat__style-menu"
          role="dialog"
          aria-label="Choose video Style"
        >
          <header className="agent-chat__style-menu-header">
            <div>
              <strong>Choose visual language</strong>
              <small>Using · {activeStyle?.title ?? "Platform Default"}</small>
            </div>
            <button
              type="button"
              aria-label="Close Style picker"
              disabled={Boolean(activatingSkillId)}
              onClick={() => setOpen(false)}
            >
              <CloseIcon />
            </button>
          </header>

          {loading ? <p className="agent-chat__style-status" role="status">Loading Styles...</p> : null}
          {error ? (
            <div className="agent-chat__style-error" role="alert">
              <span>{error}</span>
              {!catalog ? (
                <button type="button" onClick={() => void loadCatalog()}>Retry</button>
              ) : null}
            </div>
          ) : null}

          {catalog ? (
            <>
              <div className="agent-chat__style-categories" role="tablist" aria-label="Style categories">
                {categories.map((category) => (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={category.category_id === activeCategoryId}
                    key={category.category_id}
                    onClick={() => setActiveCategoryId(category.category_id)}
                  >
                    {category.title}
                  </button>
                ))}
              </div>
              {catalog.items.length > STYLE_SEARCH_THRESHOLD ? (
                <input
                  className="agent-chat__style-search"
                  type="search"
                  value={searchQuery}
                  aria-label="Search video Styles"
                  placeholder="Search Styles"
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
              ) : null}
              <div className="agent-chat__style-list">
                {visibleSkills.map((skill) => {
                  const selected = skill.skill_id === activeStyle?.skill_id
                    && skill.version === activeStyle.skill_version;
                  const activating = activatingSkillId === skill.skill_id;
                  return (
                    <StyleCard
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
                  <p className="agent-chat__style-empty">No Styles match this category and search.</p>
                ) : null}
              </div>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
