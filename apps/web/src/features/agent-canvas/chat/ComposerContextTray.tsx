import { type ReactNode, useId, useState } from "react";

import { ChevronDownIcon, ChevronUpIcon, CloseIcon } from "../../../icons.tsx";
import { AgentCanvasNodeIcon } from "../canvas/AgentCanvasNodeIcon.tsx";
import { ConversationRecoverySurface } from "./ConversationRecoverySurface.tsx";
import {
  hasComposerContext,
  type ComposerContextView,
} from "./composerContext.ts";
import type { ConversationRecoveryView } from "./conversationRecovery.ts";

export interface ComposerContextTrayProps {
  view: ComposerContextView;
  uploadIssue: ConversationRecoveryView | null;
  disabled?: boolean;
  onFocusNode(nodeId: string): void;
  onRemoveNode(nodeId: string): void;
  onRemoveAsset(assetId: string): void;
  onClearUploadIssue(): void;
}

function ContextGroup({
  id,
  title,
  className = "",
  children,
}: {
  id: string;
  title: string;
  className?: string;
  children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(true);
  return (
    <section className={`agent-chat__context-group ${className}`.trim()}>
      <button
        type="button"
        className="agent-chat__context-group-toggle"
        aria-expanded={expanded}
        aria-controls={id}
        aria-label={`${expanded ? "Hide" : "Show"} ${title} context`}
        onClick={() => setExpanded((current) => !current)}
      >
        <span>{title}</span>
        {expanded ? <ChevronDownIcon /> : <ChevronUpIcon />}
      </button>
      {expanded ? <div id={id} className="agent-chat__context-group-body">{children}</div> : null}
    </section>
  );
}

export function ComposerContextTray({
  view,
  uploadIssue,
  disabled = false,
  onFocusNode,
  onRemoveNode,
  onRemoveAsset,
  onClearUploadIssue,
}: ComposerContextTrayProps) {
  const [expanded, setExpanded] = useState(false);
  const contextGroupsId = useId();
  if (!hasComposerContext(view) && !uploadIssue) return null;

  return (
    <section className="agent-chat__context-tray" aria-label="Message context">
      <button
        type="button"
        className="agent-chat__context-summary"
        aria-expanded={expanded}
        aria-controls={contextGroupsId}
        aria-label={expanded ? "Hide message context" : "Show message context"}
        onClick={() => setExpanded((current) => !current)}
      >
        <span>
          {view.skill ? <b>Skill · {view.skill.title}</b> : null}
          {view.assets.length ? <b>Assets · {view.assets.length}</b> : null}
          {view.nodes.length ? <b>Nodes · {view.nodes.length}</b> : null}
          {view.uploadState === "uploading" ? <b>Uploading</b> : null}
        </span>
        {expanded ? <ChevronDownIcon /> : <ChevronUpIcon />}
      </button>

      {view.uploadState === "uploading" ? (
        <div className="agent-chat__context-uploading" role="status">
          Uploading context asset…
        </div>
      ) : null}

      {uploadIssue ? (
        <ConversationRecoverySurface
          recovery={uploadIssue}
          onDismiss={onClearUploadIssue}
        />
      ) : null}

      {expanded ? (
        <div className="agent-chat__context-groups" id={contextGroupsId}>
          {view.skill ? (
            <ContextGroup id={`${contextGroupsId}-skill`} title="Skill" className="is-skill">
              <div className="agent-chat__context-skill">
                <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" />
                <span>
                  <strong>{view.skill.title}</strong>
                  <small>{view.skill.summary}</small>
                </span>
              </div>
            </ContextGroup>
          ) : null}

          {view.assets.length ? (
            <ContextGroup id={`${contextGroupsId}-assets`} title="Assets">
              <div className="agent-chat__context-list">
                {view.assets.map((asset) => (
                  <div className="agent-chat__context-item" key={asset.assetId}>
                    {asset.thumbnailUrl ? <img src={asset.thumbnailUrl} alt="" /> : <span aria-hidden="true" />}
                    <span>
                      <strong>{asset.displayName}</strong>
                      <small>{asset.mediaType}</small>
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove ${asset.displayName}`}
                      title={`Remove ${asset.displayName}`}
                      disabled={disabled}
                      onClick={() => onRemoveAsset(asset.assetId)}
                    >
                      <CloseIcon />
                    </button>
                  </div>
                ))}
              </div>
            </ContextGroup>
          ) : null}

          {view.nodes.length ? (
            <ContextGroup id={`${contextGroupsId}-nodes`} title="Nodes">
              <div className="agent-chat__context-list">
                {view.nodes.map((node) => (
                  <div className="agent-chat__context-item" key={node.nodeId}>
                    <AgentCanvasNodeIcon nodeType={node.nodeType} />
                    <button
                      type="button"
                      className="agent-chat__context-focus"
                      aria-label={`Focus ${node.title}`}
                      onClick={() => onFocusNode(node.nodeId)}
                    >
                      <strong>{node.title}</strong>
                      <small>{node.nodeType}</small>
                    </button>
                    <button
                      type="button"
                      aria-label={`Remove ${node.title}`}
                      title={`Remove ${node.title}`}
                      disabled={disabled}
                      onClick={() => onRemoveNode(node.nodeId)}
                    >
                      <CloseIcon />
                    </button>
                  </div>
                ))}
              </div>
            </ContextGroup>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
