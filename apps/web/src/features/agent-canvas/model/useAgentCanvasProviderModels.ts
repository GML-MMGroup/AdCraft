import { useEffect, useState } from "react";

import { api } from "../../../api/client.ts";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

const MODEL_PICKER_NODE_TYPES = new Set<CanvasNodeV2["node_type"]>([
  "text",
  "script",
  "image",
  "video",
  "audio",
]);

/**
 * The backend filters its catalog by the complete node/input contract. The
 * canvas intentionally never reconstructs provider compatibility locally.
 */
export function useAgentCanvasProviderModels(
  _workflow: AgentCanvasWorkflowV2 | null,
  node: CanvasNodeV2 | null,
) {
  const [models, setModels] = useState<ProviderModelSummaryV1[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nodeType = node && MODEL_PICKER_NODE_TYPES.has(node.node_type)
    ? node.node_type
    : null;

  useEffect(() => {
    if (!nodeType) {
      setModels([]);
      setLoading(false);
      setError(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api.listProviderModels({ node_type: nodeType })
      .then((response) => {
        if (!cancelled) setModels(response.items);
      })
      .catch((loadError) => {
        if (cancelled) return;
        setModels([]);
        setError(loadError instanceof Error ? loadError.message : "Compatible models could not be loaded.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nodeType]);

  return { models, loading, error };
}
