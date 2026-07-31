import { useCallback, useEffect, useRef, useState } from "react";

import {
  V2_AUTHORING_DRAFT_DISCARDED_EVENT,
  type V2AuthoringConflictResolution,
} from "../../../api/v2AuthoringConflictEvents.ts";
import { isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type {
  AgentCanvasImageLibraryCategoryV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { normalizeProviderParameters } from "../model/providerModels.ts";
import type { AgentCanvasInlineWorkbenchProps } from "./workbenchTypes.ts";

function defaultLibraryCategory(node: CanvasNodeV2): AgentCanvasImageLibraryCategoryV2 {
  const role = node.creative_role.toLocaleLowerCase();
  if (role.includes("scene")) return "scene";
  if (role.includes("product") || role.includes("prop")) return "prop";
  return "character";
}

function errorMessage(error: unknown): string {
  if (isV2ApiError(error) && error.code === "provider_input_unsupported") {
    return `Provider input unsupported: ${error.message}`;
  }
  return error instanceof Error ? error.message : "The node could not be updated.";
}

function structuredText(node: CanvasNodeV2): string {
  const preferredKey = node.node_type === "script" ? "script_text" : "content";
  const preferred = node.structured_content[preferredKey];
  if (typeof preferred === "string") return preferred;
  const fallback = node.node_type === "script"
    ? node.structured_content.content
    : node.structured_content.text;
  return typeof fallback === "string" ? fallback : "";
}

export function useNodeWorkbenchDraft({
  workflow,
  node,
  patchNode,
  onRun,
  onSaveVariation,
  onDiscardVariation,
  onMaterializeVariation,
  onSaveImageToLibrary,
}: Pick<
  AgentCanvasInlineWorkbenchProps,
  | "workflow"
  | "node"
  | "patchNode"
  | "onRun"
  | "onSaveVariation"
  | "onDiscardVariation"
  | "onMaterializeVariation"
  | "onSaveImageToLibrary"
>) {
  const [title, setTitle] = useState(node.variation_draft?.title ?? node.title);
  const [prompt, setPrompt] = useState(
    node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "",
  );
  const [textContent, setTextContent] = useState(structuredText(node));
  const [modelId, setModelId] = useState(node.variation_draft?.model_id ?? node.model_id ?? "");
  const initialParameterState = normalizeProviderParameters(
    node.node_type,
    node.variation_draft?.parameters ?? node.parameters,
  );
  const [parameters, setParameters] = useState<Record<string, unknown>>(
    initialParameterState.parameters,
  );
  const [parameterMigrationRequired, setParameterMigrationRequired] = useState(
    initialParameterState.migrated,
  );
  const [libraryCategory, setLibraryCategory] = useState<AgentCanvasImageLibraryCategoryV2>(
    defaultLibraryCategory(node),
  );
  const [libraryName, setLibraryName] = useState(node.title);
  const [librarySaved, setLibrarySaved] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const draftNodeIdRef = useRef(node.node_id);

  const isReadyMedia = ["image", "video", "audio"].includes(node.node_type) && node.status === "ready";
  const editsTextContent = node.node_type === "text" || node.node_type === "script";
  const editsGenerationPrompt = ["image", "video", "audio"].includes(node.node_type);
  const usesProvider = ["script", "image", "video", "audio"].includes(node.node_type);

  const restoreFromNode = useCallback(() => {
    setTitle(node.variation_draft?.title ?? node.title);
    setPrompt(node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "");
    setTextContent(structuredText(node));
    setModelId(node.variation_draft?.model_id ?? node.model_id ?? "");
    const parameterState = normalizeProviderParameters(
      node.node_type,
      node.variation_draft?.parameters ?? node.parameters,
    );
    setParameters(parameterState.parameters);
    setParameterMigrationRequired(parameterState.migrated);
    setLibraryCategory(defaultLibraryCategory(node));
    setLibraryName(node.title);
    setLibrarySaved(false);
    setError(null);
  }, [node]);

  useEffect(() => {
    const changedNode = draftNodeIdRef.current !== node.node_id;
    if (!changedNode && dirty) return;
    draftNodeIdRef.current = node.node_id;
    restoreFromNode();
    if (changedNode) setDirty(false);
  }, [dirty, node, restoreFromNode]);

  useEffect(() => {
    const discardConflictDraft = (event: Event) => {
      const resolution = (event as CustomEvent<V2AuthoringConflictResolution>).detail;
      if (
        resolution?.action !== "discard"
        || resolution.target.resource !== "workflow"
        || resolution.target.id !== workflow.workflow_id
        || !(resolution.operationPath.split("?", 1)[0] ?? "").includes(
          `/nodes/${encodeURIComponent(node.node_id)}`,
        )
      ) return;
      restoreFromNode();
      setDirty(false);
    };
    window.addEventListener(V2_AUTHORING_DRAFT_DISCARDED_EVENT, discardConflictDraft as EventListener);
    return () => window.removeEventListener(
      V2_AUTHORING_DRAFT_DISCARDED_EVENT,
      discardConflictDraft as EventListener,
    );
  }, [node, restoreFromNode, workflow.workflow_id]);

  const perform = async (action: () => Promise<unknown>): Promise<boolean> => {
    setPending(true);
    setError(null);
    try {
      await action();
      return true;
    } catch (actionError) {
      setError(errorMessage(actionError));
      return false;
    } finally {
      setPending(false);
    }
  };

  const save = async (): Promise<boolean> => {
    if (isReadyMedia) {
      if (!prompt.trim()) {
        setError("Enter a generation prompt before creating a variation.");
        return false;
      }
      const saved = await perform(() => onSaveVariation(node.node_id, {
        title: title.trim() || `${node.title} variation`,
        generation_prompt: prompt.trim(),
        model_id: modelId || null,
        parameters,
      }));
      if (saved) {
        setDirty(false);
        setParameterMigrationRequired(false);
      }
      return saved;
    }

    const contentKey = node.node_type === "script" ? "script_text" : "content";
    const saved = await perform(() => patchNode(node.node_id, {
      title: title.trim() || node.title,
      ...(editsGenerationPrompt ? { generation_prompt: prompt } : {}),
      ...(usesProvider ? { model_id: modelId || null, parameters } : {}),
      ...(editsTextContent ? {
        structured_content: {
          ...node.structured_content,
          [contentKey]: textContent,
        },
      } : {}),
    }));
    if (saved) {
      setDirty(false);
      setParameterMigrationRequired(false);
    }
    return saved;
  };

  const run = async () => {
    if ((dirty || parameterMigrationRequired) && !(await save())) return;
    await perform(() => onRun(node));
  };

  const materializeVariation = async (action: "create_draft" | "generate") => {
    if ((dirty || parameterMigrationRequired || !node.variation_draft) && !(await save())) return;
    await perform(() => onMaterializeVariation(node, action));
  };

  const discardVariation = async () => {
    const discarded = await perform(() => onDiscardVariation(node.node_id));
    if (!discarded) return;
    restoreFromNode();
    setDirty(false);
  };

  const saveImageToLibrary = async () => {
    if (!node.output_asset_id) return;
    const displayName = libraryName.trim();
    if (!displayName) {
      setError("Enter a name before saving this image.");
      return;
    }
    const saved = await perform(() => onSaveImageToLibrary(node.output_asset_id!, {
      category: libraryCategory,
      display_name: displayName,
    }));
    if (saved) setLibrarySaved(true);
  };

  return {
    title,
    setTitle: (value: string) => { setTitle(value); setDirty(true); },
    prompt,
    setPrompt: (value: string) => { setPrompt(value); setDirty(true); },
    textContent,
    setTextContent: (value: string) => { setTextContent(value); setDirty(true); },
    modelId,
    setModelId: (value: string) => { setModelId(value); setDirty(true); },
    parameters,
    setParameters: (value: Record<string, unknown>) => {
      const parameterState = normalizeProviderParameters(node.node_type, value);
      setParameters(parameterState.parameters);
      setParameterMigrationRequired(parameterState.migrated);
      setDirty(true);
    },
    libraryCategory,
    setLibraryCategory: (value: AgentCanvasImageLibraryCategoryV2) => {
      setLibraryCategory(value);
      setLibrarySaved(false);
    },
    libraryName,
    setLibraryName: (value: string) => { setLibraryName(value); setLibrarySaved(false); },
    librarySaved,
    pending,
    error,
    dirty,
    isReadyMedia,
    editsTextContent,
    editsGenerationPrompt,
    usesProvider,
    perform,
    save,
    run,
    materializeVariation,
    discardVariation,
    saveImageToLibrary,
  };
}

export type NodeWorkbenchDraft = ReturnType<typeof useNodeWorkbenchDraft>;
