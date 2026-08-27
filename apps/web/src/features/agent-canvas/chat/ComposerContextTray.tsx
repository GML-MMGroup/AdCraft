import { useState } from "react";

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
  onFocusNode(nodeId: string): void;
  onRemoveNode(nodeId: string): void;
  onRemoveAsset(assetId: string): void;
  onClearUploadIssue(): void;
}

export function ComposerContextTray({
  view,
  uploadIssue,
  onFocusNode,
  onRemoveNode,
  onRemoveAsset,
  onClearUploadIssue,
}: ComposerContextTrayProps) {
  const [expanded, setExpanded] = useState(false);
  if (!hasComposerContext(view) && !uploadIssue) return null;

  return (
    <section className="agent-chat__context-tray" aria-label="Message context">
      <button
        type="button"
        className="agent-chat__context-summary"
        aria-expanded={expanded}
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
        <div className="agent-chat__context-groups">
          {view.skill ? (
            <section className="agent-chat__context-group is-skill">
              <h4>Skill</h4>
              <div className="agent-chat__context-skill">
                <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" />
                <span>
                  <strong>{view.skill.title}</strong>
                  <small>{view.skill.summary}</small>
                </span>
              </div>
            </section>
          ) : null}

          {view.assets.length ? (
            <section className="agent-chat__context-group">
              <h4>Assets</h4>
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
                      onClick={() => onRemoveAsset(asset.assetId)}
                    >
                      <CloseIcon />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {view.nodes.length ? (
            <section className="agent-chat__context-group">
              <h4>Nodes</h4>
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
                      onClick={() => onRemoveNode(node.nodeId)}
                    >
                      <CloseIcon />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
