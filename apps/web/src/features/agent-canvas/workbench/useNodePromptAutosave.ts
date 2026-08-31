import { useCallback, useEffect, useRef, useState } from "react";

import { isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type { CanvasNodePatchRequestV2 } from "../../../types-v2.ts";
import type { PatchNode } from "./workbenchTypes.ts";

export type NodePromptAutosaveStatus = "clean" | "dirty" | "saving" | "saved" | "conflict";

const DEBOUNCE_MS = 500;

function persistedPrompt(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function useNodePromptAutosave({
  nodeId,
  value,
  enabled,
  patchNode,
  onConflict,
  onError,
}: {
  nodeId: string;
  value: string;
  enabled: boolean;
  patchNode: PatchNode;
  onConflict?: () => Promise<void> | void;
  onError?: (error: unknown) => void;
}) {
  const [status, setStatus] = useState<NodePromptAutosaveStatus>("clean");
  const [lastSavedValue, setLastSavedValue] = useState<string | null>(persistedPrompt(value));
  const latestValueRef = useRef(value);
  const persistedValueRef = useRef<string | null>(persistedPrompt(value));
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flushPromiseRef = useRef<Promise<boolean> | null>(null);
  const localEditedRef = useRef(false);
  const mountedRef = useRef(true);
  const nodeIdRef = useRef(nodeId);

  latestValueRef.current = value;

  const safeSetStatus = useCallback((next: NodePromptAutosaveStatus) => {
    if (mountedRef.current) setStatus(next);
  }, []);

  const flush = useCallback(async (): Promise<boolean> => {
    if (!enabled) return true;
    if (flushPromiseRef.current) return flushPromiseRef.current;
    const promise = (async () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      while (true) {
        const nextValue = persistedPrompt(latestValueRef.current);
        if (nextValue === persistedValueRef.current) {
          localEditedRef.current = false;
          safeSetStatus(nextValue === null ? "clean" : "saved");
          return true;
        }
        const valueBeingSaved = nextValue;
        safeSetStatus("saving");
        try {
          const patch: CanvasNodePatchRequestV2 = { generation_prompt: valueBeingSaved };
          await patchNode(nodeIdRef.current, patch, { coalesce: true });
          persistedValueRef.current = valueBeingSaved;
          if (mountedRef.current) setLastSavedValue(valueBeingSaved);
          if (persistedPrompt(latestValueRef.current) !== valueBeingSaved) {
            safeSetStatus("dirty");
            continue;
          }
          safeSetStatus(valueBeingSaved === null ? "clean" : "saved");
          return true;
        } catch (error) {
          if (isV2ApiError(error) && (error.status === 412 || error.status === 428)) {
            safeSetStatus("conflict");
            if (mountedRef.current) await onConflict?.();
            return false;
          }
          safeSetStatus("dirty");
          if (mountedRef.current) onError?.(error);
          return false;
        }
      }
    })();
    flushPromiseRef.current = promise;
    try {
      return await promise;
    } finally {
      if (flushPromiseRef.current === promise) flushPromiseRef.current = null;
    }
  }, [enabled, onConflict, onError, patchNode, safeSetStatus]);

  const schedule = useCallback((nextValue: string) => {
    latestValueRef.current = nextValue;
    if (!enabled) return;
    localEditedRef.current = true;
    safeSetStatus("dirty");
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void flush();
    }, DEBOUNCE_MS);
  }, [enabled, flush, safeSetStatus]);

  const retry = useCallback(async () => {
    if (!enabled) return true;
    safeSetStatus("dirty");
    return flush();
  }, [enabled, flush, safeSetStatus]);

  const discard = useCallback(() => {
    const nextValue = lastSavedValue ?? "";
    latestValueRef.current = nextValue;
    persistedValueRef.current = lastSavedValue;
    localEditedRef.current = false;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    safeSetStatus(lastSavedValue === null ? "clean" : "saved");
    return nextValue;
  }, [lastSavedValue, safeSetStatus]);

  useEffect(() => {
    if (nodeIdRef.current === nodeId) return;
    nodeIdRef.current = nodeId;
    const initialValue = latestValueRef.current;
    persistedValueRef.current = persistedPrompt(initialValue);
    localEditedRef.current = false;
    setLastSavedValue(persistedPrompt(initialValue));
    setStatus("clean");
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    return () => {
      void flush();
    };
  }, [flush, nodeId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      void flush();
    };
  }, [flush]);

  return {
    status,
    lastSavedValue,
    hasPending: status === "dirty" || status === "saving",
    hasLocalChanges: localEditedRef.current,
    schedule,
    flush,
    retry,
    discard,
  };
}
