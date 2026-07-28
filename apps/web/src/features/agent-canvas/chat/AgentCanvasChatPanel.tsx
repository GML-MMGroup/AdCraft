import { useMemo, useState } from "react";

import { AssetsIcon, CloseIcon, DocumentIcon, EditIcon, SendIcon } from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasPositionV2,
  CanvasRuntimeEventV2,
  ChatProposalCardV2,
  ConceptOptionV2,
} from "../../../types-v2.ts";
import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";
import "./agent-canvas-chat.css";

export function AgentCanvasChatPanel({
  workflow,
  chatRevision,
  chatEvents,
  proposalPosition,
  onFocusNode,
}: {
  workflow: AgentCanvasWorkflowV2;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  proposalPosition: CanvasPositionV2;
  onFocusNode: (nodeId: string) => void;
}) {
  const chat = useAgentCanvasChat({
    workflow,
    chatRevision,
    chatEvents,
    proposalPosition,
  });
  const [draft, setDraft] = useState("");
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionedNodeIds, setMentionedNodeIds] = useState<string[]>([]);
  const [mentionedAssetIds, setMentionedAssetIds] = useState<string[]>([]);
  const imageAssets = useMemo(
    () => workflow.assets.filter((asset) => asset.media_type === "image"),
    [workflow.assets],
  );

  async function send() {
    const text = draft.trim();
    if (!text || chat.state.sending) return;
    const request = {
      text,
      mentionedNodeIds,
      mentionedImageAssetIds: mentionedAssetIds,
    };
    setDraft("");
    setMentionOpen(false);
    setMentionedNodeIds([]);
    setMentionedAssetIds([]);
    await chat.actions.submit(request);
  }

  function toggleValue(value: string, selected: string[], setSelected: (next: string[]) => void) {
    setSelected(selected.includes(value)
      ? selected.filter((item) => item !== value)
      : [...selected, value]);
  }

  return (
    <aside className="agent-chat" aria-label="AdCraft Video Agent">
      <header className="agent-chat__header">
        <div>
          <strong>AdCraft Video Agent</strong>
          <span>{chat.state.sending ? "Thinking" : "Ready"}</span>
        </div>
      </header>

      <div className="agent-chat__timeline" aria-live="polite">
        {chat.state.loading && !chat.state.items.length ? (
          <div className="agent-chat__empty">Loading conversation...</div>
        ) : null}
        {!chat.state.loading && !chat.state.items.length ? (
          <div className="agent-chat__empty">Describe the ad you want to build.</div>
        ) : null}
        {chat.state.items.map((item) => {
          if (item.item_type === "message") {
            return (
              <div
                className={`agent-chat__message agent-chat__message--${item.speaker === "user" ? "user" : "agent"}`}
                key={`message-${item.message_id}`}
              >
                <span>{item.speaker === "user" ? "You" : "AdCraft Video Agent"}</span>
                <p>{item.text}</p>
              </div>
            );
          }
          if (item.item_type === "expert_activity") {
            return (
              <div className={`agent-chat__activity is-${item.status}`} key={`activity-${item.activity_id}`}>
                <i aria-hidden="true" />
                <span>{item.label} {item.status === "working" ? "is working" : item.status}</span>
              </div>
            );
          }
          if (item.item_type === "artifact") {
            return (
              <button
                className="agent-chat__artifact"
                key={`artifact-${item.artifact_id}`}
                type="button"
                onClick={() => onFocusNode(item.node_id)}
              >
                <DocumentIcon />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.summary}</small>
                </span>
                <b>View Script</b>
              </button>
            );
          }
          return (
            <ProposalCard
              key={`proposal-${item.proposal.proposal_id}`}
              card={item}
              pending={chat.state.actingProposalId === item.proposal.proposal_id}
              onSelect={chat.actions.selectProposal}
              onRevise={chat.actions.reviseProposal}
              onSkip={chat.actions.skipProposal}
            />
          );
        })}
      </div>

      {chat.state.error ? (
        <div className="agent-chat__error" role="alert">
          <span>{chat.state.error}</span>
          {chat.state.failedDraft ? (
            <button type="button" onClick={() => void chat.actions.submit(chat.state.failedDraft!)}>
              Retry
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="agent-chat__composer">
        {(mentionedNodeIds.length || mentionedAssetIds.length) ? (
          <div className="agent-chat__mentions">
            {mentionedNodeIds.map((nodeId) => {
              const node = workflow.nodes.find((item) => item.node_id === nodeId);
              return (
                <button
                  type="button"
                  key={nodeId}
                  onClick={() => setMentionedNodeIds((current) => current.filter((item) => item !== nodeId))}
                >
                  @{node?.title ?? nodeId}<CloseIcon />
                </button>
              );
            })}
            {mentionedAssetIds.map((assetId) => {
              const asset = imageAssets.find((item) => item.asset_id === assetId);
              return (
                <button
                  type="button"
                  key={assetId}
                  onClick={() => setMentionedAssetIds((current) => current.filter((item) => item !== assetId))}
                >
                  @{asset?.display_name ?? assetId}<CloseIcon />
                </button>
              );
            })}
          </div>
        ) : null}
        <textarea
          value={draft}
          placeholder="Ask AdCraft Video Agent..."
          aria-label="Message AdCraft Video Agent"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="agent-chat__composer-actions">
          <button
            type="button"
            className={mentionOpen ? "is-active" : ""}
            aria-label="Mention node or image asset"
            title="Mention node or image asset"
            onClick={() => setMentionOpen((current) => !current)}
          >
            @
          </button>
          <button
            type="button"
            className="agent-chat__send"
            aria-label="Send message"
            title="Send message"
            disabled={!draft.trim() || chat.state.sending}
            onClick={() => void send()}
          >
            <SendIcon />
          </button>
        </div>
        {mentionOpen ? (
          <div className="agent-chat__mention-menu">
            <section>
              <h4>Nodes</h4>
              {workflow.nodes.map((node) => (
                <button
                  type="button"
                  key={node.node_id}
                  className={mentionedNodeIds.includes(node.node_id) ? "is-selected" : ""}
                  onClick={() => toggleValue(node.node_id, mentionedNodeIds, setMentionedNodeIds)}
                >
                  <DocumentIcon />
                  <span>{node.title}</span>
                  <small>{node.node_type}</small>
                </button>
              ))}
            </section>
            <section>
              <h4>Image assets</h4>
              {imageAssets.map((asset) => (
                <button
                  type="button"
                  key={asset.asset_id}
                  className={mentionedAssetIds.includes(asset.asset_id) ? "is-selected" : ""}
                  onClick={() => toggleValue(asset.asset_id, mentionedAssetIds, setMentionedAssetIds)}
                >
                  <AssetsIcon />
                  <span>{asset.display_name}</span>
                  <small>image</small>
                </button>
              ))}
            </section>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

export function ProposalCard({
  card,
  pending,
  onSelect,
  onRevise,
  onSkip,
}: {
  card: ChatProposalCardV2;
  pending: boolean;
  onSelect: (proposalId: string, optionId: string, nextAction: "generate_now" | "continue_planning") => Promise<void>;
  onRevise: (proposalId: string, instruction: string) => Promise<void>;
  onSkip: (proposalId: string) => Promise<void>;
}) {
  const [selected, setSelected] = useState<ConceptOptionV2 | null>(null);
  const [selectionConfirmed, setSelectionConfirmed] = useState(false);
  const [revision, setRevision] = useState("");
  const [revising, setRevising] = useState(false);
  const proposal = card.proposal;
  return (
    <article className="agent-chat__proposal">
      <header>
        <strong>{proposal.specialist
          .split("_")
          .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
          .join(" ")}</strong>
        <span>{proposal.status}</span>
      </header>
      <div className="agent-chat__options">
        {proposal.options.map((option) => (
          <button
            type="button"
            key={option.option_id}
            className={selected?.option_id === option.option_id ? "is-selected" : ""}
            disabled={proposal.status !== "pending" || pending}
            onClick={() => {
              setSelected(option);
              setSelectionConfirmed(false);
            }}
          >
            <strong>{option.display_name}</strong>
            <span>{option.summary_prompt}</span>
          </button>
        ))}
      </div>
      {proposal.status === "pending" ? (
        <div className="agent-chat__proposal-actions">
          {selected && !selectionConfirmed ? (
            <button type="button" disabled={pending} onClick={() => setSelectionConfirmed(true)}>
              Select
            </button>
          ) : selected ? (
            <>
              <button type="button" disabled={pending} onClick={() => void onSelect(proposal.proposal_id, selected.option_id, "generate_now")}>
                Generate now
              </button>
              <button type="button" disabled={pending} onClick={() => void onSelect(proposal.proposal_id, selected.option_id, "continue_planning")}>
                Continue planning
              </button>
            </>
          ) : null}
          <button type="button" disabled={pending} title="Revise options" onClick={() => setRevising((current) => !current)}>
            <EditIcon />Revise
          </button>
          <button type="button" disabled={pending} onClick={() => void onSkip(proposal.proposal_id)}>Skip</button>
        </div>
      ) : null}
      {revising ? (
        <form
          className="agent-chat__revision"
          onSubmit={(event) => {
            event.preventDefault();
            void onRevise(proposal.proposal_id, revision);
            setRevision("");
            setRevising(false);
          }}
        >
          <input
            value={revision}
            onChange={(event) => setRevision(event.target.value)}
            placeholder="Describe the change"
            aria-label="Proposal revision"
          />
          <button type="submit" disabled={!revision.trim() || pending}><SendIcon /></button>
        </form>
      ) : null}
    </article>
  );
}
