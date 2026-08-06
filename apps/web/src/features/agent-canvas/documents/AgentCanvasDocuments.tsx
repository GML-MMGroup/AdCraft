import { useCallback, useEffect, useMemo, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { CloseIcon, DocumentIcon } from "../../../icons.tsx";
import type {
  AgentWorkingDocumentKindV2,
  AgentWorkingDocumentV2,
  CanvasRuntimeEventV2,
  ChatAgentDocumentReferenceV2,
} from "../../../types-v2.ts";
import "./agent-canvas-documents.css";

function documentError(error: unknown): string {
  if (isV2ApiError(error)) {
    if (error.code === "agent_document_not_found") return "This Agent Document is no longer available.";
    if (error.code === "agent_document_workflow_mismatch") return "This document belongs to another workflow.";
    if (error.code === "agent_document_kind_unsupported") return "This document type is not supported.";
  }
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Agent Documents could not be loaded.";
}

function documentEventRevision(events: CanvasRuntimeEventV2[], documentId?: string): number {
  return events.reduce((latest, event) => {
    if (documentId && event.payload?.document_id !== documentId) return latest;
    const revision = event.payload?.revision;
    return typeof revision === "number" && Number.isInteger(revision)
      ? Math.max(latest, revision)
      : latest;
  }, 0);
}

function nodeRoleLabel(role: string): string {
  return role.split("_").map((part) => (
    `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`
  )).join(" ");
}

function seconds(value: number): string {
  return Number.isInteger(value) ? `${value}s` : `${value.toFixed(1)}s`;
}

function AgentCanvasDocumentContent({
  document,
  onFocusNode,
}: {
  document: AgentWorkingDocumentV2;
  onFocusNode: (nodeId: string) => void;
}) {
  if (document.kind === "anchor_registry") {
    return (
      <article className="agent-document-card agent-document-card--anchors">
        <header>
          <span><DocumentIcon /></span>
          <div>
            <strong>{document.title}</strong>
            <small>Anchor Registry · revision {document.revision}</small>
          </div>
        </header>
        {document.content.anchors.length ? (
          <ul className="agent-document-card__anchors">
            {document.content.anchors.map((anchor) => (
              <li key={anchor.alias}>
                <div>
                  <code>{anchor.alias}</code>
                  <span className={`is-${anchor.availability}`}>{anchor.availability}</span>
                </div>
                <strong>{anchor.display_name}</strong>
                <small>{nodeRoleLabel(anchor.anchor_type)}</small>
                <p>{anchor.summary}</p>
                {anchor.source_kind === "node" && anchor.source_id ? (
                  <button
                    type="button"
                    aria-label={`Open ${anchor.display_name} node`}
                    onClick={() => onFocusNode(anchor.source_id!)}
                  >
                    Open source
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="agent-document-card__empty">No anchors recorded yet.</p>
        )}
      </article>
    );
  }

  const content = document.content;
  return (
    <article className="agent-document-card agent-document-card--storyboard">
      <header>
        <span><DocumentIcon /></span>
        <div>
          <strong>{document.title}</strong>
          <small>Storyboard Production Plan · revision {document.revision}</small>
        </div>
      </header>
      <div className="agent-document-card__metrics">
        <span><strong>{seconds(content.global_parameters.total_duration_seconds)}</strong>Duration</span>
        <span><strong>{content.global_parameters.aspect_ratio}</strong>Frame</span>
        <span><strong>{content.global_parameters.segment_count}</strong>Segments</span>
        <span><strong>{content.materialized_panel_cursor}/{content.rows.length}</strong>Panels ready</span>
      </div>
      <p className="agent-document-card__outline">{content.narrative_outline}</p>
      {content.segments.length ? (
        <ol className="agent-document-card__segments">
          {content.segments.map((segment) => (
            <li key={segment.sequence_id}>
              <span>{segment.order}</span>
              <div>
                <strong>{segment.narrative_goal}</strong>
                <small>{seconds(segment.start_seconds)}–{seconds(segment.end_seconds)}</small>
                <p>{segment.start_state} → {segment.end_state}</p>
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      {content.rows.length ? (
        <div className="agent-document-card__rows">
          {content.rows.map((row) => (
            <div key={`${row.sequence_id}:${row.panel_index}`}>
              <span>{row.panel_index}</span>
              <p>{row.content_beat}</p>
              <small>{row.camera_description}</small>
            </div>
          ))}
        </div>
      ) : null}
      {document.linked_nodes.length ? (
        <div className="agent-document-card__linked" aria-label="Linked canvas nodes">
          {document.linked_nodes.map((node) => {
            const plannedRole = content.node_records.find((record) => record.node_id === node.node_id)?.node_role;
            const label = nodeRoleLabel(plannedRole ?? node.creative_role);
            return (
              <button
                type="button"
                key={node.node_id}
                aria-label={`Open ${label} node`}
                onClick={() => onFocusNode(node.node_id)}
              >
                <span>{label}</span>
                <small className={`is-${node.status}`}>{node.status}</small>
              </button>
            );
          })}
        </div>
      ) : null}
    </article>
  );
}

export function AgentCanvasDocumentReferenceCard({
  workflowId,
  reference,
  documentEvents,
  onFocusNode,
}: {
  workflowId: string;
  reference: ChatAgentDocumentReferenceV2;
  documentEvents: CanvasRuntimeEventV2[];
  onFocusNode: (nodeId: string) => void;
}) {
  const [document, setDocument] = useState<AgentWorkingDocumentV2 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestEventRevision = useMemo(
    () => documentEventRevision(documentEvents, reference.document_id),
    [documentEvents, reference.document_id],
  );

  const load = useCallback(async () => {
    try {
      const next = await agentCanvasApi.agentCanvasDocument(workflowId, reference.document_id);
      setDocument(next);
      setError(null);
    } catch (loadError) {
      setError(documentError(loadError));
    }
  }, [reference.document_id, workflowId]);

  useEffect(() => {
    if (!document || reference.revision > document.revision || latestEventRevision > document.revision) {
      void load();
    }
  }, [document, latestEventRevision, load, reference.revision]);

  if (error) {
    return (
      <button type="button" className="agent-document-card__error" onClick={() => void load()}>
        {error} Retry
      </button>
    );
  }
  if (!document) return <div className="agent-document-card__loading">Loading {reference.title}...</div>;
  return <AgentCanvasDocumentContent document={document} onFocusNode={onFocusNode} />;
}

export function AgentCanvasDocumentBrowser({
  workflowId,
  documentEvents,
  onFocusNode,
}: {
  workflowId: string;
  documentEvents: CanvasRuntimeEventV2[];
  onFocusNode: (nodeId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<AgentWorkingDocumentKindV2 | undefined>(undefined);
  const [items, setItems] = useState<AgentWorkingDocumentV2[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventRevision = useMemo(() => documentEventRevision(documentEvents), [documentEvents]);

  const load = useCallback(async (cursor?: string, append = false) => {
    setLoading(true);
    setError(null);
    try {
      const page = await agentCanvasApi.listAgentCanvasDocuments(workflowId, {
        kind,
        cursor,
        limit: 20,
      });
      setItems((current) => append ? [...current, ...page.items] : page.items);
      setNextCursor(page.next_cursor);
    } catch (loadError) {
      setError(documentError(loadError));
    } finally {
      setLoading(false);
    }
  }, [kind, workflowId]);

  useEffect(() => {
    if (open) void load(undefined, false);
  }, [eventRevision, load, open]);

  return (
    <div className="agent-document-browser">
      <button
        type="button"
        className={open ? "is-active" : ""}
        aria-label="Open Agent Documents"
        title="Agent Documents"
        onClick={() => setOpen((current) => !current)}
      >
        <DocumentIcon />
      </button>
      {open ? (
        <section className="agent-document-browser__panel" aria-label="Agent Documents">
          <header>
            <div>
              <strong>Agent Documents</strong>
              <small>Read-only production records</small>
            </div>
            <button type="button" aria-label="Close Agent Documents" onClick={() => setOpen(false)}>
              <CloseIcon />
            </button>
          </header>
          <div className="agent-document-browser__filters" role="group" aria-label="Document type">
            <button type="button" className={!kind ? "is-selected" : ""} onClick={() => setKind(undefined)}>All</button>
            <button
              type="button"
              className={kind === "anchor_registry" ? "is-selected" : ""}
              aria-label="Anchor registries"
              onClick={() => setKind("anchor_registry")}
            >
              Anchors
            </button>
            <button
              type="button"
              className={kind === "storyboard_production_plan" ? "is-selected" : ""}
              aria-label="Storyboard plans"
              onClick={() => setKind("storyboard_production_plan")}
            >
              Storyboards
            </button>
          </div>
          <div className="agent-document-browser__content">
            {items.map((document) => (
              <AgentCanvasDocumentContent
                key={document.document_id}
                document={document}
                onFocusNode={onFocusNode}
              />
            ))}
            {!loading && !items.length && !error ? (
              <p className="agent-document-browser__empty">No Agent Documents yet.</p>
            ) : null}
            {loading ? <p className="agent-document-browser__loading">Loading documents...</p> : null}
            {error ? <button type="button" onClick={() => void load()}>{error} Retry</button> : null}
          </div>
          {nextCursor ? (
            <button
              type="button"
              className="agent-document-browser__more"
              aria-label="Load more documents"
              disabled={loading}
              onClick={() => void load(nextCursor, true)}
            >
              Load more
            </button>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
