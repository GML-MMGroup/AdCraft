import { createRoot } from "react-dom/client";
import type { ChatMessageV2 } from "../../src/types-v2.ts";
import { NaturalMessage } from "../../src/features/agent-canvas/chat/NaturalMessage.tsx";
import { VirtualizedTimeline } from "../../src/features/agent-canvas/chat/VirtualizedTimeline.tsx";
import { projectNaturalMessagePresentation } from "../../src/features/agent-canvas/chat/naturalMessagePresentation.ts";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

function message(id: string, speaker: ChatMessageV2["speaker"], text: string): ChatMessageV2 {
  return {
    item_type: "message", message_kind: "conversation", message_id: id,
    conversation_id: "clipping-fixture", speaker, text, linked_node_ids: [],
    script_node_id: null, proposal_id: null, capability_id: null,
    sequence: 1, created_at: "2026-09-15T00:00:00Z",
  };
}

const items = [
  message("first", "adcraft_video_agent", "Drafts are ready."),
  message("continued", "adcraft_video_agent", "Run the current Drafts before continuing guided production."),
  message("user", "user", "Continue production."),
  message("long", "adcraft_video_agent", Array.from({ length: 14 }, (_, index) => `Line ${index + 1}: Draft preparation details.`).join("\n")),
  ...Array.from({ length: 30 }, (_, index) => message(`history-${index}`, "user", `History message ${index}`)),
];
const presentation = projectNaturalMessagePresentation(items);
const firstOnly = new URLSearchParams(location.search).has("first-only");

createRoot(document.getElementById("root")!).render(
  <aside className="agent-chat" style={{ position: "relative", width: "100%", maxWidth: 640, height: 560 }}>
    <div className="agent-chat__timeline">
      <div className="agent-chat__timeline-content">
        <VirtualizedTimeline
          items={firstOnly ? [items[1]!] : items}
          getKey={item => item.message_id}
          renderItem={item => <NaturalMessage message={item} presentation={presentation.get(item.message_id)!} />}
        />
      </div>
    </div>
  </aside>,
);
