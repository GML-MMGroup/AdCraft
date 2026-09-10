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

interface PromptAutosaveSession {
  nodeId: string;
  latestValue: string;
  persistedValue: string | null;
  enabled: boolean;
  localEdited: boolean;
  timer: ReturnType<typeof setTimeout> | null;
  flushPromise: Promise<boolean> | null;
}

function createSession(nodeId: string, value: string, enabled: boolean): PromptAutosaveSession {
  return {
    nodeId,
    latestValue: value,
    persistedValue: persistedPrompt(value),
    enabled,
    localEdited: false,
    timer: null,
    flushPromise: null,
  };
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
  const sessionsRef = useRef(new Map<string, PromptAutosaveSession>());
  const activeSessionRef = useRef<PromptAutosaveSession | null>(null);
  const mountedRef = useRef(true);

  let activeSession = sessionsRef.current.get(nodeId);
  if (!activeSession) {
    activeSession = createSession(nodeId, value, enabled);
    sessionsRef.current.set(nodeId, activeSession);
  } else {
    activeSession.latestValue = value;
    activeSession.enabled = enabled;
  }
  activeSessionRef.current = activeSession;

  const setSessionStatus = useCallback((session: PromptAutosaveSession, next: NodePromptAutosaveStatus) => {
    if (mountedRef.current && activeSessionRef.current === session) setStatus(next);
  }, []);

  const flushSession = useCallback(async (session: PromptAutosaveSession): Promise<boolean> => {
    if (!session.enabled && !session.localEdited) return true;
    if (session.flushPromise) return session.flushPromise;

    const promise = (async () => {
      if (session.timer) {
        clearTimeout(session.timer);
        session.timer = null;
      }
      while (true) {
        const nextValue = persistedPrompt(session.latestValue);
        if (nextValue === session.persistedValue) {
          session.localEdited = false;
          setSessionStatus(session, nextValue === null ? "clean" : "saved");
          return true;
        }
        const valueBeingSaved = nextValue;
        setSessionStatus(session, "saving");
        try {
          const patch: CanvasNodePatchRequestV2 = { generation_prompt: valueBeingSaved };
          await patchNode(session.nodeId, patch, { coalesce: true });
          session.persistedValue = valueBeingSaved;
          session.localEdited = false;
          if (mountedRef.current && activeSessionRef.current === session) setLastSavedValue(valueBeingSaved);
          if (persistedPrompt(session.latestValue) !== valueBeingSaved) {
            session.localEdited = true;
            setSessionStatus(session, "dirty");
            continue;
          }
          setSessionStatus(session, valueBeingSaved === null ? "clean" : "saved");
          return true;
        } catch (error) {
          if (isV2ApiError(error) && (error.status === 412 || error.status === 428)) {
            setSessionStatus(session, "conflict");
            if (mountedRef.current && activeSessionRef.current === session) await onConflict?.();
            return false;
          }
          setSessionStatus(session, "dirty");
          if (mountedRef.current && activeSessionRef.current === session) onError?.(error);
          return false;
        }
      }
    })();
    session.flushPromise = promise;
    try {
      return await promise;
    } finally {
      if (session.flushPromise === promise) session.flushPromise = null;
    }
  }, [onConflict, onError, patchNode, setSessionStatus]);

  const flushSessionRef = useRef(flushSession);
  flushSessionRef.current = flushSession;

  const flush = useCallback(() => {
    const session = activeSessionRef.current;
    return session ? flushSession(session) : Promise.resolve(true);
  }, [flushSession]);

  const schedule = useCallback((nextValue: string) => {
    const session = activeSessionRef.current;
    if (!session) return;
    session.latestValue = nextValue;
    if (!session.enabled) return;
    session.localEdited = true;
    setSessionStatus(session, "dirty");
    if (session.timer) clearTimeout(session.timer);
    session.timer = setTimeout(() => {
      session.timer = null;
      void flushSession(session);
    }, DEBOUNCE_MS);
  }, [flushSession, setSessionStatus]);

  const retry = useCallback(async () => {
    const session = activeSessionRef.current;
    if (!session) return true;
    session.localEdited = true;
    setSessionStatus(session, "dirty");
    return flushSession(session);
  }, [flushSession, setSessionStatus]);

  const discard = useCallback(() => {
    const session = activeSessionRef.current;
    if (!session) return "";
    const nextValue = session.persistedValue ?? "";
    session.latestValue = nextValue;
    session.localEdited = false;
    if (session.timer) {
      clearTimeout(session.timer);
      session.timer = null;
    }
    setSessionStatus(session, session.persistedValue === null ? "clean" : "saved");
    return nextValue;
  }, [setSessionStatus]);

  useEffect(() => {
    const session = activeSessionRef.current;
    if (!session) return undefined;
    setLastSavedValue(session.persistedValue);
    setStatus("clean");
    return () => {
      void flushSessionRef.current(session);
    };
  }, [nodeId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      for (const session of sessionsRef.current.values()) {
        if (session.timer) {
          clearTimeout(session.timer);
          session.timer = null;
        }
      }
      const session = activeSessionRef.current;
      if (session) void flushSessionRef.current(session);
    };
  }, []);

  return {
    status,
    lastSavedValue,
    hasPending: status === "dirty" || status === "saving",
    hasLocalChanges: activeSessionRef.current?.localEdited ?? false,
    schedule,
    flush,
    retry,
    discard,
  };
}
