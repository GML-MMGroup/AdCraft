import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { CloseIcon, StarIcon } from "../../../icons.tsx";
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
    skill.category,
    ...skill.tags,
    ...skill.supported_use_cases,
    skill.preview?.summary ?? "",
  ].some((value) => value.toLocaleLowerCase().includes(query));
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
        aria-label={`Style: ${activeStyle?.title ?? "Platform Default"}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => void togglePicker()}
      >
        <StarIcon />
        <span>{activeStyle?.title ?? "Style"}</span>
      </button>

      {open ? (
        <section
          className="agent-chat__style-menu"
          role="dialog"
          aria-label="Choose video Style"
        >
          <header className="agent-chat__style-menu-header">
            <div>
              <strong>Video Style</strong>
              <small>Applies to future Agent-created drafts</small>
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
              <input
                className="agent-chat__style-search"
                type="search"
                value={searchQuery}
                aria-label="Search video Styles"
                placeholder="Search Styles"
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              <div className="agent-chat__style-list">
                {visibleSkills.map((skill) => {
                  const selected = skill.skill_id === activeStyle?.skill_id
                    && skill.version === activeStyle.skill_version;
                  const activating = activatingSkillId === skill.skill_id;
                  return (
                    <button
                      type="button"
                      className={`agent-chat__style-option${selected ? " is-selected" : ""}`}
                      key={`${skill.skill_id}@${skill.version}`}
                      aria-pressed={selected}
                      disabled={Boolean(activatingSkillId)}
                      onClick={() => void activateStyle(skill)}
                    >
                      {skill.preview?.media_url && skill.preview.kind === "image" ? (
                        <img src={skill.preview.media_url} alt="" />
                      ) : null}
                      {skill.preview?.media_url && skill.preview.kind === "video" ? (
                        <video src={skill.preview.media_url} muted playsInline preload="metadata" />
                      ) : null}
                      <span className="agent-chat__style-option-copy">
                        <strong>{skill.title}</strong>
                        <small>{skill.summary}</small>
                        {skill.preview?.summary ? <em>{skill.preview.summary}</em> : null}
                        <span className="agent-chat__style-tags">
                          {skill.tags.map((tag) => <i key={tag}>{tag}</i>)}
                          {skill.supported_use_cases.map((useCase) => (
                            <i className="is-use-case" key={`use-case:${useCase}`}>{useCase}</i>
                          ))}
                        </span>
                      </span>
                      <span className="agent-chat__style-option-state">
                        {activating ? "Applying..." : selected ? "Active" : ""}
                      </span>
                    </button>
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
