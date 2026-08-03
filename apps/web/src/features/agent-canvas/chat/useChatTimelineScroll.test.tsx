import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatTimelineScroll } from "./useChatTimelineScroll.ts";

function TimelineHarness({
  contentVersion,
  resetKey = "workflow-1",
}: {
  contentVersion: string;
  resetKey?: string;
}) {
  const timeline = useChatTimelineScroll({ contentVersion, resetKey });
  return (
    <div>
      <div
        data-testid="timeline"
        ref={timeline.timelineRef}
        onScroll={timeline.onTimelineScroll}
      >
        <div ref={timeline.timelineContentRef}>Messages</div>
      </div>
      {timeline.hasUnseenContent ? (
        <button type="button" onClick={timeline.followLatest}>Jump to latest</button>
      ) : null}
    </div>
  );
}

function mockTimelineGeometry(
  element: HTMLElement,
  geometry: { scrollHeight: number; clientHeight: number },
) {
  Object.defineProperty(element, "scrollHeight", {
    configurable: true,
    get: () => geometry.scrollHeight,
  });
  Object.defineProperty(element, "clientHeight", {
    configurable: true,
    get: () => geometry.clientHeight,
  });
}

describe("useChatTimelineScroll", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("follows new content at the bottom without pulling users away from history", () => {
    const view = render(<TimelineHarness contentVersion="initial" />);
    const element = screen.getByTestId("timeline");
    const geometry = { scrollHeight: 1_000, clientHeight: 400 };
    mockTimelineGeometry(element, geometry);

    view.rerender(<TimelineHarness contentVersion="loaded" />);
    expect(element.scrollTop).toBe(600);

    element.scrollTop = 220;
    fireEvent.scroll(element);
    geometry.scrollHeight = 1_120;
    view.rerender(<TimelineHarness contentVersion="new-message" />);

    expect(element.scrollTop).toBe(220);
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Jump to latest" }));
    expect(element.scrollTop).toBe(720);
    expect(screen.queryByRole("button", { name: "Jump to latest" })).toBeNull();
  });

  it("resumes following when the user manually returns near the bottom", () => {
    const view = render(<TimelineHarness contentVersion="initial" />);
    const element = screen.getByTestId("timeline");
    const geometry = { scrollHeight: 1_000, clientHeight: 400 };
    mockTimelineGeometry(element, geometry);

    element.scrollTop = 585;
    fireEvent.scroll(element);
    geometry.scrollHeight = 1_100;
    view.rerender(<TimelineHarness contentVersion="new-message" />);

    expect(element.scrollTop).toBe(700);
    expect(screen.queryByRole("button", { name: "Jump to latest" })).toBeNull();
  });

  it("keeps the latest content anchored when the timeline viewport resizes", () => {
    let resizeCallback: ResizeObserverCallback | null = null;
    class ResizeObserverMock {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }

      observe() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);

    const view = render(<TimelineHarness contentVersion="initial" />);
    const element = screen.getByTestId("timeline");
    const geometry = { scrollHeight: 1_000, clientHeight: 400 };
    mockTimelineGeometry(element, geometry);
    view.rerender(<TimelineHarness contentVersion="loaded" />);
    expect(element.scrollTop).toBe(600);

    geometry.clientHeight = 300;
    act(() => resizeCallback?.([], {} as ResizeObserver));
    expect(element.scrollTop).toBe(700);

    element.scrollTop = 200;
    fireEvent.scroll(element);
    geometry.clientHeight = 250;
    act(() => resizeCallback?.([], {} as ResizeObserver));
    expect(element.scrollTop).toBe(200);
  });
});
