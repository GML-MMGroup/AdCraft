import { useEffect, useMemo, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProviderModelCapabilityV2,
} from "../../../types-v2.ts";
import { providerInputTypes, usesMediaProvider } from "./providerModels.ts";

export function useAgentCanvasProviderModels(
  workflow: AgentCanvasWorkflowV2 | null,
  node: CanvasNodeV2 | null,
) {
  const [capabilities, setCapabilities] = useState<ProviderModelCapabilityV2[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputTypes = useMemo(
    () => workflow && node ? providerInputTypes(workflow, node.node_id) : [],
    [node, workflow],
  );
  const inputSignature = inputTypes.join(",");
  const nodeType = usesMediaProvider(node) && (node.status === "draft" || node.status === "failed")
    ? node.node_type
    : null;

  useEffect(() => {
    if (!nodeType) {
      setCapabilities([]);
      setLoading(false);
      setError(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void agentCanvasApi.agentCanvasProviderCapabilities({
      output_type: nodeType,
      input_types: inputSignature ? inputSignature.split(",") : ["text"],
    }).then((items) => {
      if (!cancelled) setCapabilities(items);
    }).catch((loadError) => {
      if (cancelled) return;
      setCapabilities([]);
      setError(
        isV2ApiError(loadError) && loadError.code === "provider_input_unsupported"
          ? `Provider input unsupported: ${loadError.message}`
          : loadError instanceof Error
          ? loadError.message
          : "Compatible provider models could not be loaded.",
      );
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [inputSignature, nodeType]);

  return { capabilities, loading, error };
}
