import { textFromWorkflowOutput } from "../../../workflow/runtimeResults.ts";

export function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function scheduleIdleTask(task: () => void) {
  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
    cancelIdleCallback?: (handle: number) => void;
  };
  if (idleWindow.requestIdleCallback) {
    const handle = idleWindow.requestIdleCallback(task, { timeout: 1200 });
    return () => idleWindow.cancelIdleCallback?.(handle);
  }
  const handle = window.setTimeout(task, 220);
  return () => window.clearTimeout(handle);
}

export function textFromUnknown(value: unknown): string {
  return textFromWorkflowOutput(value);
}

export function formatEditableJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

export function formatJson(value: unknown) {
  const text = JSON.stringify(value, null, 2);
  return text.length > 1400 ? `${text.slice(0, 1400)}\n...` : text;
}

export function uniqueStringList(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

export function formatSavedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
}

export function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}
