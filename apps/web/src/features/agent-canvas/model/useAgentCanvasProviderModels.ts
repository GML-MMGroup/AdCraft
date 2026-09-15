import { useEffect, useSyncExternalStore } from "react";

import type {
  ModelDefaultPurpose,
  ModelDefaultsResponseV1,
  ProviderModelSummaryV1,
} from "../../../api/providerRegistry.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import {
  providerModelDefaults,
  providerModelsForNodeType,
  type ModelPickerNodeType,
} from "./providerModelResources.ts";

const MODEL_PICKER_NODE_TYPES = new Set<CanvasNodeV2["node_type"]>([
  "text",
  "script",
  "image",
  "video",
  "audio",
]);

const EMPTY_MODELS: ProviderModelSummaryV1[] = [];
const EMPTY_CATALOG = { data: null as ProviderModelSummaryV1[] | null, error: null, pending: false };
const EMPTY_DEFAULTS = { data: null as ModelDefaultsResponseV1 | null, error: null, pending: false };
const getEmptyCatalog = () => EMPTY_CATALOG;
const getEmptyDefaults = () => EMPTY_DEFAULTS;
const subscribeToNothing = () => () => {};

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
  const nodeType = node && node.execution_mode !== "source_only" && MODEL_PICKER_NODE_TYPES.has(node.node_type)
    ? node.node_type as ModelPickerNodeType
    : null;
  const purpose = modelPurposeForNodeType(nodeType);
  const nodeId = nodeType ? node?.node_id : null;
  const catalogResource = nodeType ? providerModelsForNodeType(nodeType) : null;
  const defaultsResource = nodeType ? providerModelDefaults : null;
  const catalog = useSyncExternalStore(
    catalogResource?.subscribe ?? subscribeToNothing,
    catalogResource?.getSnapshot ?? getEmptyCatalog,
    getEmptyCatalog,
  );
  const defaults = useSyncExternalStore(
    defaultsResource?.subscribe ?? subscribeToNothing,
    defaultsResource?.getSnapshot ?? getEmptyDefaults,
    getEmptyDefaults,
  );

  useEffect(() => {
    if (!nodeId || !catalogResource || !defaultsResource) return;
    void catalogResource.ensureFresh();
    void defaultsResource.ensureFresh();
    const revalidateOnFocus = () => {
      void catalogResource.ensureFresh(true);
      void defaultsResource.ensureFresh(true);
    };
    window.addEventListener("focus", revalidateOnFocus);
    return () => window.removeEventListener("focus", revalidateOnFocus);
  }, [catalogResource, defaultsResource, nodeId]);

  return {
    models: catalog.data ?? EMPTY_MODELS,
    defaultModelRef: purpose ? defaults.data?.defaults[purpose] ?? null : null,
    loading: Boolean(nodeType && (
      (catalog.data === null && catalog.error === null)
      || (defaults.data === null && defaults.error === null)
    )),
    error: catalog.error ?? (defaults.error ? "Default model could not be loaded." : null),
  };
}
