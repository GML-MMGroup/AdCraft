import { afterEach, expect, it, vi } from "vitest";
import { createConnectionEffectStore } from "./connectionEffectStore";
import { canvasConnectionColor } from "./connectionColor";

afterEach(() => vi.useRealTimers());
it("replaces a burst on the same node and removes effects after their lifetime", () => {
  vi.useFakeTimers();
  const store = createConnectionEffectStore();
  store.publish("w", "n", "first", "gold");
  vi.advanceTimersByTime(500);
  store.publish("w", "n", "second", "blue");
  vi.advanceTimersByTime(500);
  expect(store.get("w", "n")?.connectionId).toBe("second");
  expect(store.get("other-workflow", "n")).toBeNull();
  vi.advanceTimersByTime(451);
  expect(store.get("w", "n")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});
it("clears listeners' snapshots and timers when leaving the workflow", () => {
  vi.useFakeTimers();
  const store = createConnectionEffectStore();
  const subscriber = vi.fn();
  const unsubscribe = store.subscribe(subscriber);
  store.publish("a", "n", "first", "gold");
  store.clear();
  expect(store.get("a", "n")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
  expect(subscriber).toHaveBeenCalledTimes(2);
  unsubscribe();
  store.publish("b", "n", "other", "blue");
  expect(subscriber).toHaveBeenCalledTimes(2);
  store.clear();
});
it("chooses a stable source color independently of connection order", () => {
  const original = canvasConnectionColor("node-a");
  canvasConnectionColor("node-b");
  expect(canvasConnectionColor("node-a")).toBe(original);
  expect(original).toMatch(/^#[A-Fa-f0-9]{6}$/);
  expect(new Set(Array.from({ length: 10 }, (_, i) => canvasConnectionColor(`node-${i}`))).size).toBeGreaterThan(3);
});
