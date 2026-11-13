import { afterEach, describe, expect, it, vi } from "vitest";
import { CutiaSaveQueue } from "./saveQueue.ts";
import { editingFixture } from "./fixtures.test-support.ts";

afterEach(() => vi.useRealTimers());
describe("Cutia saves", () => {
  it("does not write when merely opening or flushing an unchanged project", async () => {
    const { snapshot } = editingFixture(); const save = vi.fn();
    const queue = new CutiaSaveQueue(snapshot, save, vi.fn());
    queue.enqueue(snapshot); await queue.flush();
    expect(save).not.toHaveBeenCalled();
  });

  it("serializes slow saves and persists the newest edit before close/export flush completes", async () => {
    vi.useFakeTimers();
    const { snapshot } = editingFixture();
    let resolve!: () => void;
    const save = vi.fn().mockImplementationOnce(() => new Promise<void>((done) => { resolve = done; })).mockResolvedValue(undefined);
    const queue = new CutiaSaveQueue(snapshot, save, vi.fn());
    const first = structuredClone(snapshot); first.project.settings.fps = 24;
    queue.enqueue(first); const flush = queue.flush();
    const second = structuredClone(first); second.project.settings.fps = 25;
    const third = structuredClone(second); third.project.settings.fps = 60;
    queue.enqueue(second); queue.enqueue(third);
    expect(save).toHaveBeenCalledTimes(1);
    resolve(); await flush;
    expect(save).toHaveBeenCalledTimes(2); expect(save.mock.calls[1][0].project.settings.fps).toBe(60);
    expect(queue.dirty).toBe(false); queue.dispose();
  });

  it("retains failed edits and blocks export/close until an explicit retry succeeds", async () => {
    vi.useFakeTimers(); const { snapshot } = editingFixture();
    const save = vi.fn().mockRejectedValueOnce(new Error("Save conflict")).mockResolvedValue(undefined);
    const queue = new CutiaSaveQueue(snapshot, save, vi.fn());
    const next = structuredClone(snapshot); next.project.settings.fps = 60;
    queue.enqueue(next);
    await expect(queue.flush()).rejects.toThrow("Save conflict");
    expect(queue.dirty).toBe(true);
    await expect(queue.flush()).rejects.toThrow("Save conflict"); expect(save).toHaveBeenCalledTimes(1);
    await queue.retry(); expect(queue.dirty).toBe(false); expect(save.mock.calls[1][0]).toEqual(next);
    queue.dispose();
  });
});
