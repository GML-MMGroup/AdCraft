import { useState } from "react";
import { createRoot } from "react-dom/client";

import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../src/types-v2.ts";
import { ReferenceSourceDecisionDock } from "../../src/features/agent-canvas/chat/ReferenceSourceDecisionDock.tsx";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

const workflowId = "workflow-reference-source-mock";

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-reference-source-mock",
  workflow_id: workflowId,
  session_id: "session-reference-source-mock",
  checkpoint_id: "checkpoint-reference-source-mock",
  kind: "reference_source",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 12,
  revision: 4,
  title: "Choose a reference",
  context: "Use a Character reference.",
  content: {
    content_kind: "reference_source",
    reference_kind: "character_main",
    target_node_id: "character-main-1",
    target_node_revision: 3,
    occurrence_id: "character-occurrence-1",
    question: "Choose a Character reference image.",
    use_reference_label: "Use reference",
    skip_reference_label: "Skip reference",
    expected_guidance_revision: 13,
  },
  allowed_actions: ["use_reference", "skip_reference"],
  submit_path: `/api/v2/workflows/${workflowId}/chat/interactions/interaction-reference-source-mock/submit`,
  created_at: "2026-09-02T00:00:00Z",
  updated_at: "2026-09-02T00:00:00Z",
};

function AcceptanceHarness() {
  const [submitted, setSubmitted] = useState<GuidedInteractionSubmitRequestV1 | null>(null);

  const submit = async (request: GuidedInteractionSubmitRequestV1): Promise<boolean> => {
    await agentCanvasApi.submitAgentCanvasGuidedInteraction(
      workflowId,
      interaction.interaction_id,
      request,
      "mock-guided-reference-source",
    );
    setSubmitted(request);
    return true;
  };

  return (
    <main className="reference-source-mock">
      <ReferenceSourceDecisionDock
        interaction={interaction}
        occurrenceLabel="Character 1"
        pending={false}
        issue={null}
        onSubmit={submit}
      />
      {submitted ? (
        <output data-testid="submitted-request">{JSON.stringify(submitted)}</output>
      ) : null}
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .reference-source-mock { width: min(100% - 32px, 720px); margin: 24px auto; font-family: Inter, sans-serif; }
  .reference-source-mock output { display: block; margin-top: 16px; color: #a3a3a3; font: 12px monospace; white-space: pre-wrap; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);
