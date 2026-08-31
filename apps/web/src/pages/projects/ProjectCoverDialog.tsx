import { useMemo, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { CloseIcon, ConfirmIcon, ImageIcon } from "../../icons.tsx";
import type { ProjectListItem } from "./ProjectList.tsx";
import { useAgentCanvasAssets } from "../../features/agent-canvas/assets/useAgentCanvasAssets.ts";
import { StableMediaPreview } from "../../workflow/StableMediaPreview.tsx";

type ProjectCoverSelection = { assetId: string; versionId: string } | null;

export function ProjectCoverDialog({
  project,
  onClose,
  onUpdateCover,
}: {
  project: ProjectListItem;
  onClose: () => void;
  onUpdateCover: (projectId: string, selection: ProjectCoverSelection) => Promise<void>;
}) {
  const assets = useAgentCanvasAssets({ workflowId: project.workflowId, scope: "project", mediaType: "all" });
  const [selection, setSelection] = useState<ProjectCoverSelection>(project.cover
    ? { assetId: project.cover.assetId, versionId: project.cover.versionId }
    : null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const candidates = useMemo(
    () => assets.items.filter((item) => (item.mediaType === "image" || item.mediaType === "video") && item.status === "ready" && Boolean(item.identity.versionId)),
    [assets.items],
  );

  async function submit() {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onUpdateCover(project.projectId, selection);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update the project cover.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleBackdropPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget && !submitting) onClose();
  }

  return createPortal(
    <div className="project-cover-backdrop" onPointerDown={handleBackdropPointerDown}>
      <div className="project-cover-dialog" role="dialog" aria-modal="true" aria-labelledby="project-cover-title" aria-busy={submitting}>
        <header className="project-cover-dialog__header">
          <div>
            <span className="project-cover-dialog__eyebrow">Project cover</span>
            <h2 id="project-cover-title">{project.name}</h2>
          </div>
          <button type="button" className="project-cover-dialog__close" aria-label="Close cover picker" onClick={onClose} disabled={submitting}><CloseIcon /></button>
        </header>
        {assets.loading ? <p className="project-cover-dialog__status">Loading project assets…</p> : null}
        {assets.error ? <p className="project-cover-dialog__error" role="alert">{assets.error}</p> : null}
        {!assets.loading && !candidates.length ? <p className="project-cover-dialog__status">No ready image or video assets are available.</p> : null}
        <div className="project-cover-grid" role="listbox" aria-label="Project cover assets" aria-busy={assets.loading}>
          {candidates.map((item) => {
            const versionId = item.identity.versionId;
            if (!versionId) return null;
            const selected = selection?.assetId === item.identity.assetId && selection?.versionId === versionId;
            return (
              <button
                key={`${item.identity.assetId}:${versionId}`}
                type="button"
                role="option"
                aria-selected={selected}
                className={`project-cover-option${selected ? " is-selected" : ""}`}
                onClick={() => setSelection({ assetId: item.identity.assetId, versionId })}
                disabled={submitting}
              >
                {item.previewUrl ? <StableMediaPreview src={item.previewUrl} alt="" loading="lazy" /> : <ImageIcon aria-hidden="true" />}
                <span>{item.displayName}</span>
              </button>
            );
          })}
        </div>
        {error ? <p className="project-cover-dialog__error" role="alert">{error}</p> : null}
        <footer className="project-cover-dialog__actions">
          <button type="button" className="project-cover-action project-cover-action--clear" onClick={() => setSelection(null)} disabled={submitting || selection === null}>Clear cover</button>
          <button type="button" className="project-cover-action project-cover-action--save" onClick={() => void submit()} disabled={submitting || (selection === null && !project.cover) || (selection?.assetId === project.cover?.assetId && selection?.versionId === project.cover?.versionId)}>
            {submitting ? "Saving…" : <><ConfirmIcon /> Save cover</>}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
