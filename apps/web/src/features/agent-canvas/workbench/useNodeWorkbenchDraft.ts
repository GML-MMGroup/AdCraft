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
import { canvasAuthoringErrorMessage } from "../canvas/canvasErrorMessage.ts";
import type { AgentCanvasInlineWorkbenchProps } from "./workbenchTypes.ts";
import { useNodePromptAutosave } from "./useNodePromptAutosave.ts";

function defaultLibraryCategory(node: CanvasNodeV2): AgentCanvasImageLibraryCategoryV2 {
  const role = node.creative_role.toLocaleLowerCase();
  if (role.includes("scene")) return "scene";
  if (role.includes("product") || role.includes("prop")) return "prop";
  return "character";
}

type WorkbenchErrorAction = "open_api_space" | "choose_model" | "sync_models" | null;

function errorState(error: unknown): { message: string; action: WorkbenchErrorAction } {
  if (!isV2ApiError(error)) {
    return {
      message: error instanceof Error ? error.message : "The node could not be updated.",
      action: null,
    };
  }
  const code = error.code ?? "";
  const action: WorkbenchErrorAction = ["provider_credentials_missing", "provider_credentials_invalid", "model_not_configured", "model_default_not_configured", "agent_model_incompatible"].includes(code)
    ? "open_api_space"
    : ["model_not_found", "model_unavailable", "model_capability_mismatch", "binding_model_incompatible", "model_selection_invalid"].includes(code)
      ? "choose_model"
      : code === "model_catalog_sync_failed"
        ? "sync_models"
        : null;
  return { message: canvasAuthoringErrorMessage(error), action };
}

function structuredText(node: CanvasNodeV2): string {
  const preferred = node.structured_content.content;
  if (typeof preferred === "string") return preferred;
  const legacyScript = node.structured_content.script_text;
  if (typeof legacyScript === "string") return legacyScript;
  const fallback = node.structured_content.text;
  return typeof fallback === "string" ? fallback : "";
}

export function useNodeWorkbenchDraft({
  workflow,
  node,
  visibleStatus,
  patchNode,
  onRun,
  onSaveVariation,
  onDiscardVariation,
  onMaterializeVariation,
  onSaveImageToLibrary,
  onWorkflowRefresh,
}: Pick<
  AgentCanvasInlineWorkbenchProps,
  | "workflow"
  | "node"
  | "visibleStatus"
  | "patchNode"
  | "onRun"
  | "onSaveVariation"
  | "onDiscardVariation"
  | "onMaterializeVariation"
  | "onSaveImageToLibrary"
  | "onWorkflowRefresh"
>) {
  const [title, setTitle] = useState(node.variation_draft?.title ?? node.title);
  const [prompt, setPrompt] = useState(
    node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "",
  );
  const [textContent, setTextContent] = useState(structuredText(node));
  const [modelSelectionMode, setModelSelectionMode] = useState(
    node.variation_draft?.model_selection_mode ?? node.model_selection_mode ?? "default",
  );
  const [modelRef, setModelRef] = useState(
    node.variation_draft?.model_ref ?? node.model_ref,
  );
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
  const [errorAction, setErrorAction] = useState<WorkbenchErrorAction>(null);
  const [dirty, setDirty] = useState(false);
  const draftNodeIdRef = useRef(node.node_id);

  const isReadyMedia = ["image", "video", "audio"].includes(node.node_type) && node.status === "ready";
  const isWorldSetting = node.node_type === "text" && node.creative_role === "world_setting";
  const effectiveStatus = visibleStatus ?? node.status;
  const isRunnableScript = node.node_type === "script"
    && (effectiveStatus === "draft" || effectiveStatus === "failed");
  const isRunnableText = node.node_type === "text"
    && !isWorldSetting
    && (effectiveStatus === "draft" || effectiveStatus === "failed");
  const editsTextContent = (node.node_type === "text" && isWorldSetting)
    || (node.node_type === "script" && !isRunnableScript)
    || (node.node_type === "text" && !isRunnableText);
  const editsGenerationPrompt = isRunnableScript
    || isRunnableText
    || ["image", "video", "audio"].includes(node.node_type);
  const canAutosavePrompt = editsGenerationPrompt
    && !isReadyMedia
    && (effectiveStatus === "draft" || effectiveStatus === "failed");
  const usesProvider = !isWorldSetting && ["text", "script", "image", "video", "audio"].includes(node.node_type);
  const nodeForRun = node.node_type === "script" && effectiveStatus !== node.status
    ? { ...node, status: effectiveStatus }
    : node;

  const handlePromptConflict = useCallback(async () => {
    setError("This prompt was changed elsewhere. Review the refreshed workflow, then retry or discard your local text.");
    await onWorkflowRefresh?.();
  }, [onWorkflowRefresh]);
  const handlePromptError = useCallback((promptError: unknown) => {
    const nextError = errorState(promptError);
    setError(nextError.message);
    setErrorAction(nextError.action);
  }, []);
  const promptAutosave = useNodePromptAutosave({
    nodeId: node.node_id,
    value: prompt,
    enabled: canAutosavePrompt,
    patchNode,
    onConflict: handlePromptConflict,
    onError: handlePromptError,
  });

  const restoreFromNode = useCallback(() => {
    setTitle(node.variation_draft?.title ?? node.title);
    setPrompt(node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "");
    setTextContent(structuredText(node));
    setModelSelectionMode(node.variation_draft?.model_selection_mode ?? node.model_selection_mode ?? "default");
    setModelRef(node.variation_draft?.model_ref ?? node.model_ref);
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
    setErrorAction(null);
  }, [node]);

  useEffect(() => {
    const changedNode = draftNodeIdRef.current !== node.node_id;
    const authoritativePrompt = (node.variation_draft?.generation_prompt ?? node.generation_prompt ?? "").trim() || null;
    const waitingForPromptResponse = !changedNode
      && promptAutosave.lastSavedValue !== authoritativePrompt;
    if (!changedNode && (
      dirty
      || promptAutosave.status === "dirty"
      || promptAutosave.status === "saving"
      || promptAutosave.status === "conflict"
      || promptAutosave.hasLocalChanges
      || waitingForPromptResponse
    )) return;
    draftNodeIdRef.current = node.node_id;
    restoreFromNode();
    if (changedNode) setDirty(false);
  }, [dirty, node, promptAutosave.hasLocalChanges, promptAutosave.lastSavedValue, promptAutosave.status, restoreFromNode]);

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
      const nextError = errorState(actionError);
      setError(nextError.message);
      setErrorAction(nextError.action);
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
        model_selection_mode: modelSelectionMode,
        model_ref: modelSelectionMode === "explicit" ? modelRef : null,
        parameters,
      }));
      if (saved) {
        setDirty(false);
        setParameterMigrationRequired(false);
      }
      return saved;
    }

    if (isWorldSetting) {
      if (!textContent.trim()) {
        setError("World Setting content cannot be empty.");
        return false;
      }
      const saved = await perform(() => patchNode(node.node_id, {
        structured_content: {
          ...node.structured_content,
          content: textContent,
        },
      }));
      if (saved) setDirty(false);
      return saved;
    }

    if (canAutosavePrompt && !(await promptAutosave.flush())) return false;

    if (isRunnableScript && !prompt.trim()) {
      setError("Enter a prompt before running this node.");
      return false;
    }

    const saved = await perform(() => patchNode(node.node_id, {
      title: title.trim() || node.title,
      ...(usesProvider ? {
        model_selection_mode: modelSelectionMode,
        model_ref: modelSelectionMode === "explicit" ? modelRef : null,
        parameters,
      } : {}),
      ...(editsTextContent ? {
        structured_content: {
          ...node.structured_content,
          content: textContent,
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
    if (canAutosavePrompt) {
      if (!(await promptAutosave.flush())) return;
      if (!prompt.trim()) {
        setError("Enter a prompt before running this node.");
        return;
      }
    }
    if ((dirty || parameterMigrationRequired) && !(await save())) return;
    const runNode = editsGenerationPrompt
      ? { ...nodeForRun, generation_prompt: prompt.trim() || null }
      : nodeForRun;
    await perform(() => onRun(runNode));
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
    setPrompt: (value: string) => {
      setPrompt(value);
      if (canAutosavePrompt) promptAutosave.schedule(value);
      else setDirty(true);
    },
    textContent,
    setTextContent: (value: string) => { setTextContent(value); setDirty(true); },
    modelSelectionMode,
    modelRef,
    setModelSelection: (mode: "default" | "explicit", ref: string | null) => {
      setModelSelectionMode(mode);
      setModelRef(mode === "explicit" ? ref : null);
      setDirty(true);
    },
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
    errorAction,
    dirty,
    promptSaveStatus: promptAutosave.status,
    promptSaveError: promptAutosave.status === "conflict" ? "Prompt conflict needs your decision." : null,
    flushPrompt: promptAutosave.flush,
    retryPromptSave: promptAutosave.retry,
    discardPromptChanges: () => {
      const discarded = promptAutosave.discard();
      restoreFromNode();
      setPrompt(discarded);
      setDirty(false);
      setError(null);
      return discarded;
    },
    refreshWorkflow: onWorkflowRefresh,
    isReadyMedia,
    isWorldSetting,
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
