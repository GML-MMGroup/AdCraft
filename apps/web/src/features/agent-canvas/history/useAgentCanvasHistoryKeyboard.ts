import { useEffect } from "react";
import type { useAgentCanvasHistory } from "./useAgentCanvasHistory.ts";

export function useAgentCanvasHistoryKeyboard(
  history: Pick<ReturnType<typeof useAgentCanvasHistory>, "undo" | "redo" | "busy" | "state">,
  layoutPreviewActive: boolean,
) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || layoutPreviewActive || history.busy || event.altKey) return;
      const target = event.composedPath()[0] ?? event.target;
      if (target instanceof Element && (
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
        || target.closest("[contenteditable], .nokey")
      )) return;
      const key = event.key.toLowerCase();
      const direction = key === "z" && (event.ctrlKey || event.metaKey)
        ? event.shiftKey ? "redo" : "undo"
        : key === "y" && event.ctrlKey && !event.shiftKey ? "redo" : null;
      if (!direction || !history.state[direction].length) return;
      event.preventDefault();
      void history[direction]();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [history, layoutPreviewActive]);
}
