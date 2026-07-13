import { HistoryIcon, SyncIcon } from "../../../../icons.tsx";
import type { V2ScriptVersionSummary } from "../../../../types-v2.ts";
import type { V2ScreenplayController } from "./useV2ScreenplayController.ts";

export function V2ScreenplayVersionHistory({ controller }: { controller: V2ScreenplayController }) {
  const { state } = controller;
  const versions = [...state.versions].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const selecting = state.isSelecting;

  return <section className="v2-screenplay-history" aria-label="Script version history">
    <div className="v2-screenplay-section-heading">
      <div><h3>Version history</h3><p>Immutable saved script versions.</p></div>
      <button className="v2-screenplay-icon-button" type="button" aria-label="Refresh script version history" title="Refresh script version history" disabled={state.isLoading || selecting} onClick={() => void controller.refreshHistory()}><SyncIcon /></button>
    </div>
    {state.isLoading && versions.length === 0 ? <p className="v2-screenplay-status">Loading script versions...</p> : null}
    {!state.isLoading && versions.length === 0 ? <p className="v2-screenplay-empty">No script versions are available.</p> : null}
    {versions.map((version) => <VersionRow key={version.script_version_id} version={version} selected={version.script_version_id === state.selectedScriptVersionId} disabled={selecting || Boolean(state.conflict)} onSelect={() => void controller.selectVersion(version.script_version_id)} />)}
  </section>;
}

function VersionRow({ version, selected, disabled, onSelect }: { version: V2ScriptVersionSummary; selected: boolean; disabled: boolean; onSelect: () => void }) {
  return <article className={`v2-screenplay-version ${selected ? "is-selected" : ""}`}>
    <div className="v2-screenplay-version-heading"><HistoryIcon /><div><strong>{version.script_title || "Untitled script"}</strong><span>{selected ? "Selected" : "Saved version"}</span></div></div>
    <dl>
      <div><dt>Source</dt><dd>{sourceLabel(version.source_action)}</dd></div>
      <div><dt>Created</dt><dd>{formatTimestamp(version.created_at)}</dd></div>
      <div><dt>Changes</dt><dd>{formatDiffSummary(version.structural_diff_summary)}</dd></div>
    </dl>
    <button className="v2-screenplay-secondary-action" type="button" disabled={selected || disabled} onClick={onSelect}>{disabled && !selected ? "Applying version..." : "Use this script version"}</button>
  </article>;
}

function sourceLabel(source: V2ScriptVersionSummary["source_action"]): string { return source === "script_editor_confirm" ? "Editor confirmation" : source === "agent_chat_edit" ? "Agent edit" : "Initial planning"; }
function formatTimestamp(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); }
function formatDiffSummary(summary: Record<string, unknown>): string {
  const entries = Object.entries(summary).filter(([, value]) => value !== 0 && value !== false && value != null).slice(0, 4);
  if (!entries.length) return "No structural changes recorded.";
  return entries.map(([key, value]) => `${key.replace(/_/g, " ")}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join("; ");
}
