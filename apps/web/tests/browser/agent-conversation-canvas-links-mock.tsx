import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import type { CanvasNodeV2 } from "../../src/types-v2.ts";
import { NodeConversationAction } from "../../src/features/agent-canvas/canvas/NodeConversationAction.tsx";
import { ConversationNodeLinks } from "../../src/features/agent-canvas/chat/ConversationNodeLinks.tsx";
import { CurrentProductionStep } from "../../src/features/agent-canvas/chat/CurrentProductionStep.tsx";
import type { ConversationCanvasLocation } from "../../src/features/agent-canvas/chat/conversationCanvasLinks.ts";
import { StageThread } from "../../src/features/agent-canvas/chat/StageThread.tsx";
import type { StageThreadUnit } from "../../src/features/agent-canvas/chat/stageThreadProjection.ts";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";
import "../../src/features/agent-canvas/canvas/AgentCanvasNode.css";

const nodes = [
  { node_id: "storyboard-1", title: "Storyboard 01", node_type: "image" },
  { node_id: "video-1", title: "Video 01", node_type: "video" },
] as CanvasNodeV2[];

const location: ConversationCanvasLocation = {
  key: "stage:storyboard_design",
  kind: "stage_thread",
  sequence: 1,
  createdNodeIds: ["storyboard-1", "video-1"],
  updatedNodeIds: [],
  deletedNodeIds: [],
  relatedNodeIds: [],
  navigableNodeIds: ["storyboard-1", "video-1"],
};

const thread: StageThreadUnit = {
  unit_type: "stage_thread",
  key: location.key,
  capability_id: "storyboard_design",
  capability_display_name: "Storyboard Artist",
  sequence: 1,
  status: "completed",
  planning: [],
  activities: [],
  proposals: [],
  receipts: [],
  selected_option: null,
  completed_activity_count: 1,
};

function MockAcceptance() {
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [revealToken, setRevealToken] = useState<number | null>(null);
  const [conversationHighlighted, setConversationHighlighted] = useState(false);
  const sourceRef = useRef<HTMLDivElement>(null);

  const viewNodes = (nodeIds: string[]) => {
    setHighlightedNodeIds(nodeIds);
    window.setTimeout(() => setHighlightedNodeIds([]), 1500);
  };

  const showInConversation = () => {
    setChatCollapsed(false);
    setRevealToken((current) => (current ?? 0) + 1);
  };

  useEffect(() => {
    if (revealToken === null || chatCollapsed) return;
    sourceRef.current?.focus();
    setConversationHighlighted(true);
    const timer = window.setTimeout(() => setConversationHighlighted(false), 1500);
    return () => window.clearTimeout(timer);
  }, [chatCollapsed, revealToken]);

  return (
    <main className="coordination-mock">
      <section className="coordination-mock__canvas" aria-label="Canvas">
        {nodes.map((node) => (
          <div key={node.node_id} className="coordination-mock__node-wrap">
            <button
              type="button"
              className={`coordination-mock__node${highlightedNodeIds.includes(node.node_id) ? " is-conversation-highlighted" : ""}`}
              data-node-id={node.node_id}
              onClick={() => setSelectedNodeId(node.node_id)}
            >
              <span>{node.title}</span>
              <small>{node.node_type}</small>
            </button>
            {selectedNodeId === node.node_id && node.node_id === "storyboard-1" ? (
              <NodeConversationAction nodeId={node.node_id} onShowInConversation={showInConversation} />
            ) : null}
          </div>
        ))}
        <p data-testid="editor-state">No node editor opened</p>
      </section>

      {chatCollapsed ? (
        <button type="button" className="agent-chat__collapsed-trigger" onClick={() => setChatCollapsed(false)}>
          Open AdCraft Bot
        </button>
      ) : (
        <aside className="agent-chat coordination-mock__chat" aria-label="AdCraft Video Agent">
          <header className="agent-chat__header">
            <div className="agent-chat__identity">
              <strong>AdCraft Video Agent</strong>
              <span>Working</span>
            </div>
            <button type="button" className="agent-chat__collapse" onClick={() => setChatCollapsed(true)}>
              Collapse
            </button>
          </header>
          <CurrentProductionStep
            focus={{
              kind: "running",
              title: "2 video nodes are generating",
              detail: "Generation is in progress",
              actionLabel: "View on canvas",
              nodeIds: ["storyboard-1", "video-1"],
            }}
            onViewNodes={viewNodes}
          />
          <div className="agent-chat__timeline">
            <div className="agent-chat__timeline-content">
              <div
                ref={sourceRef}
                tabIndex={-1}
                data-conversation-location={location.key}
                className={`agent-chat__conversation-location${conversationHighlighted ? " is-highlighted" : ""}`}
              >
                <StageThread
                  unit={thread}
                  revealToken={revealToken}
                  result={(
                    <ConversationNodeLinks
                      location={location}
                      nodes={nodes}
                      variant="result"
                      onViewNodes={viewNodes}
                    />
                  )}
                >
                  <div>Created from the selected storyboard direction.</div>
                </StageThread>
              </div>
            </div>
          </div>
        </aside>
      )}
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { width: 100%; height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .coordination-mock { position: relative; width: 100%; height: 100%; overflow: hidden; font-family: Inter, sans-serif; }
  .coordination-mock__canvas { display: flex; height: 100%; align-items: center; justify-content: center; gap: 48px; padding-right: 390px; }
  .coordination-mock__node-wrap { display: grid; justify-items: center; gap: 12px; }
  .coordination-mock__node { display: grid; width: 220px; height: 144px; place-content: center; gap: 6px; border: 1px solid #4a4a4a; border-radius: 8px; background: #151515; color: #f5f5f5; }
  .coordination-mock__node small { color: #a3a3a3; }
  .coordination-mock__node.is-conversation-highlighted { border-color: #f5f5f5; box-shadow: 0 0 0 2px rgb(245 245 245 / 72%); }
  .coordination-mock__canvas > p { position: absolute; bottom: 24px; left: 24px; color: #707070; }
  .coordination-mock__chat { width: 390px; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<MockAcceptance />);
