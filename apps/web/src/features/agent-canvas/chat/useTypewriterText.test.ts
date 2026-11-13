import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTypewriterText } from "./useTypewriterText.ts";

describe("useTypewriterText", () => {
  let now: number;
  let nextFrame: number;
  let frames: Map<number, FrameRequestCallback>;

  beforeEach(() => {
    now = 0;
    nextFrame = 0;
    frames = new Map();
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      frames.set(++nextFrame, callback);
      return nextFrame;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  function advance(ms: number, frameMs = 16) {
    act(() => {
      for (let elapsed = 0; elapsed < ms; elapsed += frameMs) {
        now += frameMs;
        const pending = [...frames.values()];
        frames.clear();
        pending.forEach(callback => callback(now));
      }
    });
  }

  it("reveals a buffered answer progressively and finishes without a running timer", () => {
    const text = "这是一个逐步显示的回答。".repeat(6);
    const { result } = renderHook(() => useTypewriterText(text));
    expect(result.current).toBe("");
    advance(160);
    expect(result.current.length).toBeGreaterThan(0);
    expect(result.current.length).toBeLessThan(text.length);
    expect(text.startsWith(result.current)).toBe(true);
    advance(8_000);
    expect(result.current).toBe(text);
    expect(frames.size).toBe(0);
  });

  it("continues frequent streaming appends without resetting the clock or visible prefix", () => {
    const { result, rerender } = renderHook(({ text }) => useTypewriterText(text), { initialProps: { text: "开" } });
    for (let index = 1; index <= 60; index++) {
      now += 8;
      rerender({ text: "开始".repeat(index) });
      advance(8, 8);
    }
    expect(result.current.length).toBeGreaterThan(15);
    expect(result.current.length).toBeLessThan(30);
    const previous = result.current;
    rerender({ text: "开始".repeat(60) + "完成" });
    expect(result.current).toBe(previous);
    advance(8_000);
    expect(result.current.endsWith("完成")).toBe(true);
  });

  it("keeps grapheme clusters whole, including emoji and combining marks", () => {
    const characters = ["你", "👩🏽‍💻", "e\u0301", "🇨🇳", "好"];
    const { result } = renderHook(() => useTypewriterText(characters.join("")));
    for (let count = 1; count <= characters.length; count++) {
      advance(42, 42);
      expect(result.current).toBe(characters.slice(0, count).join(""));
    }
  });

  it("uses elapsed time rather than display refresh rate", () => {
    const text = "A".repeat(200);
    const first = renderHook(() => useTypewriterText(text));
    advance(480, 16);
    const length = first.result.current.length;
    first.unmount();
    const second = renderHook(() => useTypewriterText(text));
    advance(480, 8);
    expect(second.result.current.length).toBe(length);
  });

  it("keeps long answers at the same reading pace as short ones without an eight-second deadline", () => {
    const short = renderHook(() => useTypewriterText("文".repeat(300)));
    const long = renderHook(() => useTypewriterText("文".repeat(6_000)));
    advance(1_000, 20);
    expect(long.result.current.length).toBe(short.result.current.length);
    expect(long.result.current.length).toBeGreaterThan(15);
    expect(long.result.current.length).toBeLessThan(30);
    advance(8_000, 20);
    expect(long.result.current.length).toBe(short.result.current.length);
    expect(long.result.current.length).toBeLessThan(300);
  });

  it("does not speed up when a large streaming chunk arrives", () => {
    const { result, rerender } = renderHook(({ text }) => useTypewriterText(text), {
      initialProps: { text: "文".repeat(200) },
    });
    advance(1_000, 20);
    const prefix = result.current;
    rerender({ text: "文".repeat(6_000) });
    expect(result.current).toBe(prefix);
    advance(1_000, 20);
    // Whole characters can straddle the sampling boundary by one frame.
    expect(Math.abs((result.current.length - prefix.length) - prefix.length)).toBeLessThanOrEqual(1);
  });

  it("resumes after a long frame pause without dumping the buffered answer", () => {
    const { result } = renderHook(() => useTypewriterText("文".repeat(6_000)));
    advance(240);
    const beforePause = result.current.length;
    advance(60_000, 60_000);
    expect(result.current.length).toBeGreaterThan(beforePause);
    expect(result.current.length - beforePause).toBeLessThanOrEqual(3);
    const afterPause = result.current.length;
    advance(1_000, 20);
    expect(result.current.length - afterPause).toBeGreaterThan(15);
    expect(result.current.length - afterPause).toBeLessThan(30);
  });

  it("continues a live answer after it moves into its committed message and never replays it", () => {
    const cache = new Map<string, string>();
    const playback = { cache, key: "stream-1" };
    const text = "A streamed reply that continues typing after being committed.";
    const live = renderHook(() => useTypewriterText(text, { playback }));
    advance(240);
    const prefix = live.result.current;
    live.unmount();
    expect(frames.size).toBe(0);
    const committed = renderHook(() => useTypewriterText(text, { playback }));
    expect(committed.result.current).toBe(prefix);
    advance(8_000);
    committed.unmount();
    expect(renderHook(() => useTypewriterText(text, { playback })).result.current).toBe(text);
    expect(frames.size).toBe(0);
  });

  it("shows history and reduced-motion content immediately", () => {
    expect(renderHook(() => useTypewriterText("History", { animate: false })).result.current).toBe("History");
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    expect(renderHook(() => useTypewriterText("Reduced motion")).result.current).toBe("Reduced motion");
    expect(frames.size).toBe(0);
  });

  it("cancels stale frames on reset, replacement and unmount", () => {
    const { result, rerender, unmount } = renderHook(({ text }) => useTypewriterText(text), {
      initialProps: { text: "Old answer with buffered content" },
    });
    advance(160);
    rerender({ text: "" });
    expect(result.current).toBe("");
    expect(frames.size).toBe(0);
    rerender({ text: "New answer" });
    advance(160);
    rerender({ text: "Corrected final answer" });
    expect(result.current).toBe("Corrected final answer");
    expect(frames.size).toBe(0);
    rerender({ text: "Corrected final answer with more content" });
    unmount();
    expect(frames.size).toBe(0);
  });
});
