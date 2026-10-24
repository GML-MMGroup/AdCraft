import { useState } from "react";
import { createRoot } from "react-dom/client";

import { useAgentCanvasPresentationStreams } from "../../src/features/agent-canvas/runtime/useAgentCanvasPresentationStreams.ts";

function PresentationStreamLifecycle() {
  const [workflowId, setWorkflowId] = useState("workflow-1");
  const [streamIds, setStreamIds] = useState(["turn-1"]);
  const streams = useAgentCanvasPresentationStreams(workflowId, streamIds);

  return (
    <main>
      <p data-testid="workflow">{workflowId}</p>
      <button type="button" onClick={() => setStreamIds((current) => [...current, `turn-${current.length + 1}`])}>
        Add turn
      </button>
      <button type="button" onClick={() => {
        setWorkflowId("workflow-2");
        setStreamIds(["turn-1"]);
      }}>
        Switch workflow
      </button>
      {streamIds.map((streamId) => (
        <section key={streamId} aria-label={streamId}>
          <p data-testid={`${streamId}-status`}>{streams[streamId]?.status}</p>
          <p data-testid={`${streamId}-text`}>{streams[streamId]?.text}</p>
          <p data-testid={`${streamId}-cursor`}>{streams[streamId]?.last_sequence_no}</p>
        </section>
      ))}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<PresentationStreamLifecycle />);
