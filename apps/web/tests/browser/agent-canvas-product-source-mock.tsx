import { useState } from "react";
import { createRoot } from "react-dom/client";

import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../src/types-v2.ts";
import { ProductSourceDecisionDock } from "../../src/features/agent-canvas/chat/ProductSourceDecisionDock.tsx";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

const workflowId = "workflow-product-source-mock";
const timestamp = "2026-08-27T00:00:00Z";

function interaction(inputKind: "main" | "multiview"): GuidedInteractionV1 {
  return {
    interaction_id: `interaction-product-${inputKind}`,
    workflow_id: workflowId,
    session_id: "session-product-source-mock",
    checkpoint_id: `checkpoint-product-${inputKind}`,
    kind: "product_source",
    status: "open",
    response_locale: "en-US",
    expected_session_revision: 7,
    revision: 3,
    title: inputKind === "main" ? "Choose Product Main" : "Choose Product Multiview",
    context: "Use an existing image or ask the Agent to generate the Product source.",
    content: {
      content_kind: "product_source",
      input_kind: inputKind,
      question_id: `product_${inputKind}_source`,
      prompt: inputKind === "main"
        ? "Choose exactly one Product main image."
        : "Choose two to eight ordered Product images.",
      expected_guidance_revision: 11,
      min_asset_count: inputKind === "main" ? 1 : 2,
      max_asset_count: inputKind === "main" ? 1 : 8,
    },
    allowed_actions: ["select_source"],
    submit_path: `/api/v2/workflows/${workflowId}/chat/interactions/interaction-product-${inputKind}/submit`,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function AcceptanceHarness() {
  const [inputKind, setInputKind] = useState<"main" | "multiview">("main");
  const [accepted, setAccepted] = useState<{ nodeId: string; inputKind: string } | null>(null);

  const submit = async (
    request: GuidedInteractionSubmitRequestV1,
  ): Promise<boolean> => {
    const currentInteraction = interaction(inputKind);
    const response = await agentCanvasApi.submitAgentCanvasGuidedInteraction(
      workflowId,
      currentInteraction.interaction_id,
      request,
      `mock-guided-product-${inputKind}`,
    );
    setAccepted({
      nodeId: response.created_node_ids[0] ?? "missing-created-node-id",
      inputKind,
    });
    return true;
  };

  return (
    <main className="product-source-mock">
      <nav aria-label="Product source input kind">
        <button type="button" aria-pressed={inputKind === "main"} onClick={() => {
          setInputKind("main");
          setAccepted(null);
        }}>
          Product Main
        </button>
        <button type="button" aria-pressed={inputKind === "multiview"} onClick={() => {
          setInputKind("multiview");
          setAccepted(null);
        }}>
          Product Multiview
        </button>
      </nav>

      <ProductSourceDecisionDock
        key={`${workflowId}:${inputKind}`}
        interaction={interaction(inputKind)}
        pending={false}
        issue={null}
        onSubmit={submit}
      />

      {accepted ? (
        <section data-testid="source-only-product-node" aria-label="Source-only Product node">
          <strong>Product {accepted.inputKind} Image node</strong>
          <span>Ready</span>
          <span>execution_mode: source_only</span>
          <span data-testid="created-node-id">{accepted.nodeId}</span>
          <p>No Prompt, model, Run, or Variation controls.</p>
        </section>
      ) : null}
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .product-source-mock { display: grid; gap: 16px; width: min(100% - 32px, 720px); margin: 24px auto; font-family: Inter, sans-serif; }
  .product-source-mock nav { display: flex; gap: 8px; }
  .product-source-mock nav button { border: 1px solid #4a4a4a; border-radius: 7px; background: #151515; color: #f5f5f5; padding: 8px 12px; }
  .product-source-mock nav button[aria-pressed="true"] { background: #353535; }
  .product-source-mock > section { display: grid; gap: 6px; border: 1px solid #4a4a4a; border-radius: 8px; background: #151515; padding: 14px; }
  .product-source-mock > section span { color: #a3a3a3; font-size: 12px; }
  .product-source-mock > section p { margin: 4px 0 0; color: #707070; font-size: 12px; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);
