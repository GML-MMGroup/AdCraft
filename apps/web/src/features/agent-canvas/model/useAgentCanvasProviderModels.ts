import { useEffect, useState } from "react";

import { api } from "../../../api/client.ts";
import type {
  ModelDefaultPurpose,
  ProviderModelSummaryV1,
} from "../../../api/providerRegistry.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

const MODEL_PICKER_NODE_TYPES = new Set<CanvasNodeV2["node_type"]>([
  "text",
  "script",
  "image",
  "video",
  "audio",
]);

function modelPurposeForNodeType(
  nodeType: CanvasNodeV2["node_type"] | null,
): ModelDefaultPurpose | null {
  if (nodeType === "text" || nodeType === "script") return "text";
  if (nodeType === "image" || nodeType === "video" || nodeType === "audio") return nodeType;
  return null;
}

/**
 * The backend filters its catalog by the complete node/input contract. The
 * canvas intentionally never reconstructs provider compatibility locally.
 */
export function useAgentCanvasProviderModels(
  _workflow: AgentCanvasWorkflowV2 | null,
  node: CanvasNodeV2 | null,
) {
  const [models, setModels] = useState<ProviderModelSummaryV1[]>([]);
  const [defaultModelRef, setDefaultModelRef] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nodeType = node && MODEL_PICKER_NODE_TYPES.has(node.node_type)
    ? node.node_type
    : null;
  const purpose = modelPurposeForNodeType(nodeType);

  useEffect(() => {
    if (!nodeType) {
      setModels([]);
      setDefaultModelRef(null);
      setLoading(false);
      setError(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.allSettled([
      api.listProviderModels({ node_type: nodeType, include_unavailable: true }),
      api.getModelDefaults(),
    ])
      .then(([catalogResult, defaultsResult]) => {
        if (cancelled) return;
        if (catalogResult.status === "fulfilled") {
          setModels(catalogResult.value.items);
          setError(defaultsResult.status === "rejected" ? "Default model could not be loaded." : null);
        } else {
          setModels([]);
          const loadError = catalogResult.reason;
          setError(loadError instanceof Error ? loadError.message : "Compatible models could not be loaded.");
        }
        setDefaultModelRef(
          purpose && defaultsResult.status === "fulfilled"
            ? defaultsResult.value.defaults[purpose] ?? null
            : null,
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nodeType, purpose]);

  return { models, defaultModelRef, loading, error };
}
